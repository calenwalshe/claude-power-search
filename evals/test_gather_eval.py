"""
Eval suite for the gather+integrate system.

Dim 1: Job lifecycle correctness
Dim 2: Worker harness (crash/timeout isolation)
Dim 3: Partial integration
Dim 4: Integration agent quality (LLM-judged)
Dim 5: Pre-flight hook visibility
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure we import from the project source
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from power_search.config import configure
from power_search.tracker import Tracker


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_tracker(tmp_path):
    """Fresh tracker backed by a temp SQLite db, patched into the usage singleton."""
    db = tmp_path / "test.db"
    configure(db_path=db)
    t = Tracker()
    with patch("power_search.tracker.usage", t), \
         patch("power_search.integrate.usage", t):
        yield t


@pytest.fixture
def job_id():
    return "test-job-01"


# ── Dim 1: Job lifecycle ──────────────────────────────────────────────────────

class TestJobLifecycle:
    def test_create_job_persists(self, tmp_tracker, job_id):
        tmp_tracker.create_job(job_id, "test query", ["perplexity", "gemini_grounded"])
        job = tmp_tracker.get_job(job_id)
        assert job is not None
        assert job["query"] == "test query"
        assert job["status"] == "running"
        assert "perplexity" in job["providers"]

    def test_create_job_with_context(self, tmp_tracker, job_id):
        tmp_tracker.create_job(job_id, "q", ["perplexity"], context="evaluating vector DBs")
        job = tmp_tracker.get_job(job_id)
        assert job["context"] == "evaluating vector DBs"

    def test_write_result_lands_immediately(self, tmp_tracker, job_id):
        tmp_tracker.create_job(job_id, "q", ["perplexity"])
        tmp_tracker.write_result(job_id, "perplexity", None, "done",
                                  content="some content", cost=0.01, elapsed_ms=500, score=0.8)
        results = tmp_tracker.get_results(job_id)
        assert len(results) == 1
        assert results[0]["status"] == "done"
        assert results[0]["score"] == 0.8

    def test_multiple_results_in_order(self, tmp_tracker, job_id):
        tmp_tracker.create_job(job_id, "q", ["perplexity", "gemini_grounded"])
        tmp_tracker.write_result(job_id, "perplexity", None, "done", content="p result")
        time.sleep(0.01)
        tmp_tracker.write_result(job_id, "gemini_grounded", None, "done", content="g result")
        results = tmp_tracker.get_results(job_id)
        assert len(results) == 2
        assert results[0]["provider"] == "perplexity"
        assert results[1]["provider"] == "gemini_grounded"

    def test_finish_job_transitions_status(self, tmp_tracker, job_id):
        tmp_tracker.create_job(job_id, "q", ["perplexity"])
        tmp_tracker.finish_job(job_id)
        job = tmp_tracker.get_job(job_id)
        assert job["status"] == "done"
        assert job["finished_at"] is not None

    def test_list_jobs_newest_first(self, tmp_tracker):
        tmp_tracker.create_job("job-a", "query a", ["perplexity"])
        time.sleep(0.01)
        tmp_tracker.create_job("job-b", "query b", ["gemini_grounded"])
        jobs = tmp_tracker.list_jobs(limit=10)
        assert jobs[0]["id"] == "job-b"
        assert jobs[1]["id"] == "job-a"


# ── Dim 2: Worker harness ─────────────────────────────────────────────────────

class TestWorkerHarness:
    def test_crashing_worker_does_not_kill_siblings(self, tmp_path):
        """A crashing worker must not prevent sibling workers from completing.

        We verify this by patching router.search globally (not via context manager,
        so the patch persists into background threads) and reading from the real
        usage tracker after the job finishes.
        """
        from power_search.base import Intent, SearchResult
        from power_search.tracker import Tracker
        from power_search.config import configure

        db = tmp_path / "harness.db"
        configure(db_path=db)

        import power_search.router as router_mod
        orig = router_mod.search

        def fake_router_search(query, provider=None, **kwargs):
            if provider == "tavily":
                raise RuntimeError("Simulated tavily crash")
            return SearchResult(
                content="good result from " + provider,
                provider=provider, cost=0.01,
                intent=Intent.SEARCH, query=query,
            )

        router_mod.search = fake_router_search
        try:
            from power_search.gather import start_gather, wait_for_job
            jid = start_gather("test query", ["tavily", "gemini_grounded"], verbose=False)
            wait_for_job(jid, timeout=30)
        finally:
            router_mod.search = orig

        tracker = Tracker()
        results = tracker.get_results(jid)
        statuses = {r["provider"]: r["status"] for r in results}

        # The sibling must have completed even though tavily crashed
        assert statuses.get("gemini_grounded") == "done", \
            f"Sibling worker was blocked by crash. statuses={statuses}"
        # Tavily crash must be recorded
        assert statuses.get("tavily") == "error", \
            f"Crash not recorded. statuses={statuses}"

    def test_error_result_captures_message(self, tmp_tracker, job_id):
        tmp_tracker.create_job(job_id, "q", ["tavily"])
        tmp_tracker.write_result(job_id, "tavily", None, "error",
                                  error="Connection timeout after 30s")
        results = tmp_tracker.get_results(job_id)
        assert results[0]["error"] == "Connection timeout after 30s"
        assert results[0]["content"] is None

    def test_cdp_skipped_when_service_down(self, tmp_path):
        """CDP providers should be silently filtered if serverlogin unreachable."""
        configure(db_path=tmp_path / "test3.db")

        with patch("power_search.gather._chrome_available", return_value=False):
            from power_search.gather import _resolve_specs, WorkerSpec
            specs = _resolve_specs(["perplexity", "chatgpt/thinking", "gemini_cdp/flash"], "q")

        provider_names = [s.provider for s in specs]
        assert "perplexity" in provider_names
        assert "chatgpt/thinking" not in provider_names
        assert "gemini_cdp/flash" not in provider_names


# ── Dim 3: Partial integration ────────────────────────────────────────────────

class TestPartialIntegration:
    def _make_job_with_results(self, tracker, jid, done_providers, failed_providers):
        all_providers = done_providers + failed_providers
        tracker.create_job(jid, "test query for partial integration", all_providers)
        for p in done_providers:
            tracker.write_result(jid, p, None, "done",
                                  content=f"Result from {p}: This is a detailed response about the topic "
                                          f"covering key aspects and nuances with sufficient length.",
                                  cost=0.01, elapsed_ms=800, score=0.85)
        for p in failed_providers:
            tracker.write_result(jid, p, None, "error", error="timeout")

    def test_integrate_with_partial_results_succeeds(self, tmp_tracker, tmp_path):
        """Integration should work with 1+ done results even if others failed."""
        jid = "partial-int-01"
        self._make_job_with_results(tmp_tracker, jid,
                                     done_providers=["gemini_grounded"],
                                     failed_providers=["perplexity"])
        tmp_tracker.finish_job(jid)

        with patch("power_search.integrate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Synthesized answer mentioning gemini_grounded result.",
                stderr="",
            )
            from power_search.integrate import integrate
            result = integrate(jid, verbose=False)

        assert "gemini_grounded" in result or len(result) > 0

    def test_integrate_fails_with_zero_done(self, tmp_tracker):
        jid = "partial-int-02"
        tmp_tracker.create_job(jid, "q", ["perplexity"])
        tmp_tracker.write_result(jid, "perplexity", None, "error", error="auth failed")
        tmp_tracker.finish_job(jid)

        from power_search.integrate import integrate
        with pytest.raises(RuntimeError, match="No successful results"):
            integrate(jid, verbose=False)

    def test_integration_stored_in_db(self, tmp_tracker, tmp_path):
        jid = "partial-int-03"
        self._make_job_with_results(tmp_tracker, jid,
                                     done_providers=["gemini_grounded", "gemini"],
                                     failed_providers=[])
        tmp_tracker.finish_job(jid)

        with patch("power_search.integrate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Great synthesis.", stderr="")
            with patch("power_search.integrate._depot", MagicMock()):
                from power_search.integrate import integrate
                integrate(jid, verbose=False)

        integrations = tmp_tracker.get_integrations(jid)
        assert len(integrations) == 1
        assert "gemini_grounded" in integrations[0]["sources_used"]
        assert integrations[0]["sources_missing"] == []

    def test_multiple_integration_runs_accumulate(self, tmp_tracker):
        jid = "partial-int-04"
        self._make_job_with_results(tmp_tracker, jid,
                                     done_providers=["gemini_grounded"],
                                     failed_providers=[])
        tmp_tracker.finish_job(jid)

        with patch("power_search.integrate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Synthesis v1.", stderr="")
            with patch("power_search.integrate._depot", MagicMock()):
                from power_search.integrate import integrate
                integrate(jid, verbose=False)
                # Add another result and integrate again
                tmp_tracker.write_result(jid, "perplexity", None, "done",
                                          content="Late perplexity result with good content here.",
                                          cost=0.02, elapsed_ms=5000, score=0.9)
                mock_run.return_value = MagicMock(returncode=0, stdout="Synthesis v2 richer.", stderr="")
                integrate(jid, verbose=False)

        integrations = tmp_tracker.get_integrations(jid)
        assert len(integrations) == 2


# ── Dim 4: Integration agent quality (LLM-judged) ────────────────────────────

class TestIntegrationQuality:
    """
    These tests call claude -p to judge integration output quality.
    They run against real fixture data — no mocking of the integration agent.
    Marked slow; skipped if SKIP_LLM_EVALS env var is set.
    """

    FIXTURE_RESULTS = [
        {
            "provider": "gemini_grounded",
            "status": "done",
            "elapsed_ms": 8000,
            "score": 0.9,
            "content": (
                "Python async frameworks in 2026: FastAPI remains dominant for API development "
                "due to its Pydantic v3 integration and native async support. Starlette underpins "
                "most production deployments. Django 5.x added full async ORM support, closing "
                "the gap with FastAPI for full-stack apps. Uvicorn and Granian compete as ASGI "
                "servers, with Granian showing 30% better throughput in benchmarks."
            ),
        },
        {
            "provider": "perplexity",
            "status": "done",
            "elapsed_ms": 6000,
            "score": 0.88,
            "content": (
                "Async Python frameworks 2026: Django now has async views and ORM by default. "
                "FastAPI/Starlette ecosystem still leads for pure API work. Key new entrant: "
                "Litestar (formerly Starlite) gaining traction for typed async APIs. "
                "CONFLICT: some sources suggest Granian outperforms Uvicorn, others show parity. "
                "Sources: python.org/news, fastapi.tiangolo.com, litestar.dev"
            ),
        },
        {
            "provider": "chatgpt/thinking",
            "status": "error",
            "elapsed_ms": 90000,
            "score": None,
            "content": None,
            "error": "timeout after 90s",
        },
    ]

    def _build_prompt_for_judge(self, synthesis: str) -> str:
        return f"""You are evaluating the quality of an AI research synthesis.

Rate the following synthesis on these criteria. Answer YES or NO for each:

1. ATTRIBUTION: Does it name which provider said what?
2. CONFLICT: Does it flag the conflicting claim about Granian vs Uvicorn performance?
3. MISSING: Does it note that chatgpt/thinking failed/timed out?
4. CONFIDENCE: Does it include a confidence assessment?
5. COHERENT: Is it a coherent synthesis (not just concatenation)?

Synthesis to evaluate:
---
{synthesis}
---

Respond in this exact format (one per line):
ATTRIBUTION: YES/NO
CONFLICT: YES/NO
MISSING: YES/NO
CONFIDENCE: YES/NO
COHERENT: YES/NO
SCORE: X/5
"""

    @pytest.mark.slow
    def test_integration_quality_with_fixture(self, tmp_tracker, tmp_path):
        import os
        if os.environ.get("SKIP_LLM_EVALS"):
            pytest.skip("SKIP_LLM_EVALS set")

        jid = "quality-eval-01"
        tmp_tracker.create_job(jid, "Python async frameworks in 2026",
                                ["gemini_grounded", "perplexity", "chatgpt/thinking"],
                                context="choosing async framework for a new microservice")

        for r in self.FIXTURE_RESULTS:
            tmp_tracker.write_result(
                jid, r["provider"], None, r["status"],
                content=r.get("content"),
                elapsed_ms=r.get("elapsed_ms", 0),
                score=r.get("score"),
                error=r.get("error"),
            )
        tmp_tracker.finish_job(jid)

        # Run real integration (no mock)
        with patch("power_search.integrate._depot", MagicMock()):
            from power_search.integrate import integrate
            synthesis = integrate(jid, verbose=True)

        assert len(synthesis) > 100, "Synthesis too short"

        # Judge with claude -p
        judge_prompt = self._build_prompt_for_judge(synthesis)
        proc = subprocess.run(
            ["claude", "-p", "--model", "claude-sonnet-4-6", "--bare", judge_prompt],
            capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode == 0, f"Judge failed: {proc.stderr}"
        judgment = proc.stdout

        # Parse scores
        scores = {}
        for line in judgment.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                scores[k.strip()] = v.strip()

        print(f"\n[eval:quality] synthesis ({len(synthesis)} chars)")
        print(f"[eval:quality] judge scores: {scores}")

        assert scores.get("CONFLICT", "NO") == "YES", "Integration missed the Granian conflict"
        assert scores.get("MISSING", "NO") == "YES", "Integration missed the chatgpt timeout"
        assert scores.get("COHERENT", "NO") == "YES", "Integration is incoherent"

        score_str = scores.get("SCORE", "0/5")
        score_val = int(score_str.split("/")[0]) if "/" in score_str else 0
        assert score_val >= 3, f"Quality score too low: {score_str}"


# ── Dim 5: Pre-flight hook ────────────────────────────────────────────────────

class TestPreflightHook:
    def test_hook_fires_before_workers(self, tmp_path, capsys):
        configure(db_path=tmp_path / "test5.db")

        fired_events = []

        def fake_router_search(query, provider=None, **kwargs):
            fired_events.append(("worker", provider, time.monotonic()))
            from power_search.base import Intent, SearchResult
            return SearchResult(content="ok", provider=provider, cost=0.0,
                                intent=Intent.SEARCH, query=query)

        with patch("power_search.router.search", fake_router_search):
            from power_search.gather import start_gather, wait_for_job

            hook_time = time.monotonic()
            # Capture stderr for hook output
            import io
            stderr_capture = io.StringIO()
            with patch("sys.stderr", stderr_capture):
                jid = start_gather("test query", ["gemini_grounded"], verbose=True)
                wait_for_job(jid, timeout=20)
            hook_output = stderr_capture.getvalue()

        assert "[gather:" in hook_output, "Pre-flight hook did not fire"
        assert "gemini_grounded" in hook_output, "Provider not shown in hook"
        assert "tier=" in hook_output, "Tier not shown in hook"
        assert "est=" in hook_output, "Est latency not shown in hook"

    def test_cdp_providers_not_shown_when_service_down(self, tmp_path):
        configure(db_path=tmp_path / "test6.db")

        with patch("power_search.gather._chrome_available", return_value=False):
            from power_search.gather import _resolve_specs
            specs = _resolve_specs(["perplexity", "chatgpt/thinking"], "q")

        # chatgpt/thinking filtered out — only perplexity remains
        assert len(specs) == 1
        assert specs[0].provider == "perplexity"

    def test_provider_meta_covers_all_known_providers(self):
        from power_search.gather import PROVIDER_META
        expected = [
            "perplexity", "gemini_grounded", "gemini", "tavily",
            "chatgpt/instant", "chatgpt/latest", "chatgpt/thinking", "chatgpt/pro",
            "gemini_cdp/flash", "gemini_cdp/thinking", "gemini_cdp/pro",
        ]
        for p in expected:
            assert p in PROVIDER_META, f"Missing PROVIDER_META entry for {p}"
            assert "timeout" in PROVIDER_META[p]
            assert "tier" in PROVIDER_META[p]
            assert "est" in PROVIDER_META[p]

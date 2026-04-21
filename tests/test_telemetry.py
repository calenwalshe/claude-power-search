"""Tests for L0 telemetry — search_events table, route_stats, report CLI."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from power_search.config import configure
from power_search.base import Intent, SearchResult
from power_search.tracker import Tracker


@pytest.fixture
def tmp_tracker(tmp_path):
    db_path = tmp_path / "test.db"
    configure(db_path=db_path)
    return Tracker()


# ── search_events schema ───────────────────────────────────────────────────

class TestSearchEventsSchema:

    def test_record_event_stores_row(self, tmp_tracker):
        tmp_tracker.record_event(
            provider="tavily",
            intent="search",
            query="test query",
            cost=0.016,
            outcome="success",
            candidates_tried=["gemini_grounded", "tavily"],
            fallback_count=1,
            elapsed_ms=320,
        )
        rows = tmp_tracker.recent_events(1)
        assert len(rows) == 1
        r = rows[0]
        assert r["provider"] == "tavily"
        assert r["outcome"] == "success"
        assert r["fallback_count"] == 1
        assert r["candidates_tried"] == ["gemini_grounded", "tavily"]

    def test_record_event_with_error(self, tmp_tracker):
        tmp_tracker.record_event(
            provider="perplexity",
            intent="research",
            query="deep dive",
            cost=0.0,
            outcome="error",
            candidates_tried=["perplexity"],
            fallback_count=0,
            elapsed_ms=100,
            error_type="ProviderKeyError",
        )
        rows = tmp_tracker.recent_events(1)
        assert rows[0]["outcome"] == "error"
        assert rows[0]["error_type"] == "ProviderKeyError"

    def test_record_event_with_session_id(self, tmp_tracker):
        tmp_tracker.record_event(
            provider="jina",
            intent="read_url",
            query="https://example.com",
            cost=0.0001,
            outcome="success",
            candidates_tried=["jina"],
            fallback_count=0,
            elapsed_ms=200,
            session_id="sess-abc123",
        )
        rows = tmp_tracker.recent_events(1)
        assert rows[0]["session_id"] == "sess-abc123"

    def test_multiple_events_ordered_newest_first(self, tmp_tracker):
        for i in range(3):
            tmp_tracker.record_event(
                provider=f"p{i}", intent="search", query=f"q{i}",
                cost=0.01 * i, outcome="success", candidates_tried=[f"p{i}"],
                fallback_count=0, elapsed_ms=100,
            )
        rows = tmp_tracker.recent_events(3)
        assert rows[0]["provider"] == "p2"
        assert rows[2]["provider"] == "p0"


# ── route_stats ────────────────────────────────────────────────────────────

class TestRouteStats:

    def test_success_rate_per_provider(self, tmp_tracker):
        tmp_tracker.record_event("tavily", "search", "q1", 0.01, "success", ["tavily"], 0, 100)
        tmp_tracker.record_event("tavily", "search", "q2", 0.01, "success", ["tavily"], 0, 120)
        tmp_tracker.record_event("tavily", "search", "q3", 0.0,  "error",   ["tavily"], 0, 50, error_type="Timeout")

        stats = tmp_tracker.route_stats()
        tavily = next(s for s in stats if s["provider"] == "tavily")
        assert tavily["total"] == 3
        assert tavily["success"] == 2
        assert abs(tavily["success_rate"] - 2/3) < 0.01

    def test_stats_by_intent(self, tmp_tracker):
        tmp_tracker.record_event("perplexity", "research", "q1", 0.025, "success", ["perplexity"], 0, 1000)
        tmp_tracker.record_event("tavily",     "search",   "q2", 0.016, "success", ["tavily"],     0, 300)

        stats = tmp_tracker.route_stats(intent="research")
        assert all(s["intent"] == "research" for s in stats)
        providers = [s["provider"] for s in stats]
        assert "perplexity" in providers
        assert "tavily" not in providers

    def test_avg_latency_in_stats(self, tmp_tracker):
        tmp_tracker.record_event("jina", "read_url", "u1", 0.0001, "success", ["jina"], 0, 200)
        tmp_tracker.record_event("jina", "read_url", "u2", 0.0001, "success", ["jina"], 0, 400)

        stats = tmp_tracker.route_stats()
        jina = next(s for s in stats if s["provider"] == "jina")
        assert abs(jina["avg_latency_ms"] - 300) < 1

    def test_empty_db_returns_empty_stats(self, tmp_tracker):
        stats = tmp_tracker.route_stats()
        assert stats == []

    def test_fallback_rate_tracked(self, tmp_tracker):
        tmp_tracker.record_event("tavily", "search", "q1", 0.01, "success", ["gemini_grounded", "tavily"], 1, 300)
        tmp_tracker.record_event("tavily", "search", "q2", 0.01, "success", ["tavily"], 0, 200)

        stats = tmp_tracker.route_stats()
        tavily = next(s for s in stats if s["provider"] == "tavily")
        assert abs(tavily["avg_fallback_count"] - 0.5) < 0.01


# ── Router integration ─────────────────────────────────────────────────────

class TestRouterTelemetry:

    def _make_result(self, provider="tavily", cost=0.016) -> SearchResult:
        return SearchResult(
            content="result", provider=provider, cost=cost,
            intent=Intent.SEARCH, query="test",
            tokens_in=10, tokens_out=50, elapsed_ms=300,
        )

    def test_router_records_event_on_success(self, tmp_path):
        configure(db_path=tmp_path / "test.db")
        from power_search.router import Router
        from power_search.tracker import usage

        mock_provider = MagicMock()
        mock_provider.available.return_value = True
        mock_provider.search.return_value = self._make_result()

        router = Router()
        router._providers = {"tavily": mock_provider}

        with patch("power_search.router.ROUTING_TABLE", {Intent.SEARCH: ["tavily"]}), \
             patch("power_search.router.CHEAPEST_TABLE", {Intent.SEARCH: ["tavily"]}), \
             patch("power_search.router.QUALITY_TABLE", {Intent.SEARCH: ["tavily"]}):
            router.search("test query")

        events = usage.recent_events(1)
        assert len(events) == 1
        assert events[0]["outcome"] == "success"
        assert events[0]["provider"] == "tavily"

    def test_router_records_fallback_count(self, tmp_path):
        configure(db_path=tmp_path / "test.db")
        from power_search.router import Router
        from power_search.tracker import usage

        failing = MagicMock()
        failing.available.return_value = True
        failing.search.side_effect = Exception("upstream down")

        working = MagicMock()
        working.available.return_value = True
        working.search.return_value = self._make_result(provider="perplexity")

        router = Router()
        router._providers = {"gemini_grounded": failing, "perplexity": working}

        with patch("power_search.router.ROUTING_TABLE", {Intent.SEARCH: ["gemini_grounded", "perplexity"]}), \
             patch("power_search.router.CHEAPEST_TABLE", {Intent.SEARCH: ["gemini_grounded", "perplexity"]}), \
             patch("power_search.router.QUALITY_TABLE", {Intent.SEARCH: ["gemini_grounded", "perplexity"]}):
            result = router.search("test query")

        assert result.provider == "perplexity"
        events = usage.recent_events(1)
        assert events[0]["fallback_count"] == 1
        assert "gemini_grounded" in events[0]["candidates_tried"]


# ── report CLI ────────────────────────────────────────────────────────────

class TestReportCLI:

    def test_report_command_exists(self):
        from power_search.cli import COMMANDS
        assert "report" in COMMANDS

    def test_report_runs_without_error(self, tmp_path, capsys):
        configure(db_path=tmp_path / "test.db")
        t = Tracker()
        t.record_event("tavily", "search", "q", 0.016, "success", ["tavily"], 0, 300)
        t.record_event("perplexity", "research", "q2", 0.025, "error", ["perplexity"], 0, 50,
                       error_type="Timeout")

        from power_search.cli import cmd_report
        import sys
        old_argv = sys.argv
        sys.argv = ["power-search", "report"]
        try:
            ret = cmd_report()
        finally:
            sys.argv = old_argv

        assert ret == 0
        out = capsys.readouterr().out
        assert "tavily" in out
        assert "perplexity" in out

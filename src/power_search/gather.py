"""Gather engine — fan-out to multiple providers in parallel, stream results into job store."""

from __future__ import annotations

import sys
import time
import uuid
import urllib.request
import json
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass
from typing import Optional

from power_search.base import Intent, SearchResult
from power_search.tracker import usage
from power_search.critic import critique


# Per-provider timeout in seconds and estimated latency label
PROVIDER_META: dict[str, dict] = {
    "perplexity":       {"timeout": 30,   "est": "5-15s",   "tier": "fast"},
    "gemini_grounded":  {"timeout": 20,   "est": "3-10s",   "tier": "fast"},
    "gemini":           {"timeout": 30,   "est": "5-15s",   "tier": "fast"},
    "tavily":           {"timeout": 15,   "est": "2-8s",    "tier": "fast"},
    "jina":             {"timeout": 15,   "est": "2-6s",    "tier": "fast"},
    "firecrawl":        {"timeout": 30,   "est": "5-20s",   "tier": "medium"},
    "chatgpt/instant":  {"timeout": 60,   "est": "15-25s",  "tier": "medium"},
    "chatgpt/thinking": {"timeout": 180,  "est": "30-60s",  "tier": "slow"},
    "chatgpt/pro":      {"timeout": 300,  "est": "45-90s",  "tier": "slow"},
    "chatgpt/deep_research": {"timeout": 1800, "est": "5-20min", "tier": "very_slow"},
    "gemini_cdp/flash":    {"timeout": 30,  "est": "5-10s",  "tier": "fast"},
    "gemini_cdp/thinking": {"timeout": 120, "est": "15-40s", "tier": "medium"},
    "gemini_cdp/pro":      {"timeout": 240, "est": "30-90s", "tier": "slow"},
}

CHROME_QUERY_URL = "http://localhost:8765/query"


@dataclass
class WorkerSpec:
    """Describes one unit of gather work."""
    provider: str        # e.g. "perplexity" or "chatgpt/thinking"
    mode: Optional[str]  # CDP mode, None for API providers
    target: Optional[str] = None  # "chatgpt" or "gemini_cdp" for CDP workers


def _is_cdp(spec: WorkerSpec) -> bool:
    return spec.target in ("chatgpt", "gemini_cdp")


def _chrome_available() -> bool:
    try:
        req = urllib.request.Request(CHROME_QUERY_URL.replace("/query", "/"),
                                     method="GET")
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def _run_api_worker(spec: WorkerSpec, query: str, job_id: str) -> dict:
    from power_search.router import search as router_search
    from power_search.base import Intent

    meta = PROVIDER_META.get(spec.provider, {})
    timeout = meta.get("timeout", 30)
    start = time.monotonic()
    try:
        result: SearchResult = router_search(query, provider=spec.provider)
        elapsed = int((time.monotonic() - start) * 1000)
        cr = critique(result)
        score = cr.score
        usage.write_result(
            job_id=job_id, provider=spec.provider, mode=None,
            status="done", content=result.content,
            cost=result.cost, elapsed_ms=elapsed, score=score,
        )
        return {"provider": spec.provider, "status": "done", "score": score, "elapsed_ms": elapsed}
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        usage.write_result(
            job_id=job_id, provider=spec.provider, mode=None,
            status="error", error=str(e), elapsed_ms=elapsed,
        )
        return {"provider": spec.provider, "status": "error", "error": str(e)}


def _run_cdp_worker(spec: WorkerSpec, query: str, job_id: str) -> dict:
    meta = PROVIDER_META.get(f"{spec.target}/{spec.mode}", {})
    timeout = meta.get("timeout", 120)
    start = time.monotonic()
    try:
        body = json.dumps({"target": spec.target, "prompt": query, "mode": spec.mode}).encode()
        req = urllib.request.Request(
            CHROME_QUERY_URL, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())

        if result.get("error"):
            raise RuntimeError(f"CDP error: {result['error']}")

        content = result.get("text", "")
        elapsed = int((time.monotonic() - start) * 1000)
        provider_key = f"{spec.target}/{spec.mode}"

        # Simple quality heuristic for CDP results (no SearchResult object)
        score = min(1.0, len(content) / 500) if content else 0.0

        usage.write_result(
            job_id=job_id, provider=provider_key, mode=spec.mode,
            status="done", content=content,
            cost=0.0, elapsed_ms=elapsed, score=score,
        )
        return {"provider": provider_key, "status": "done", "score": score, "elapsed_ms": elapsed}
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        provider_key = f"{spec.target}/{spec.mode}"
        usage.write_result(
            job_id=job_id, provider=provider_key, mode=spec.mode,
            status="error", error=str(e), elapsed_ms=elapsed,
        )
        return {"provider": provider_key, "status": "error", "error": str(e)}


def _resolve_specs(providers: list[str], query: str) -> list[WorkerSpec]:
    """Convert provider name strings into WorkerSpecs, filtering unavailable CDP providers."""
    cdp_up = None  # lazy check
    specs = []
    for p in providers:
        if "/" in p:
            # CDP provider e.g. "chatgpt/thinking" or "gemini_cdp/flash"
            target, mode = p.split("/", 1)
            if cdp_up is None:
                cdp_up = _chrome_available()
            if not cdp_up:
                print(f"[gather] SKIP {p} — serverlogin not reachable", file=sys.stderr)
                continue
            specs.append(WorkerSpec(provider=p, mode=mode, target=target))
        else:
            specs.append(WorkerSpec(provider=p, mode=None, target=None))
    return specs


def start_gather(
    query: str,
    providers: list[str],
    context: Optional[str] = None,
    job_id: Optional[str] = None,
    verbose: bool = True,
) -> str:
    """
    Fire parallel workers for each provider. Returns job_id immediately.
    Workers write results to job store as they land (non-blocking).
    Set verbose=True to print the pre-flight hook and progress to stderr.
    """
    if job_id is None:
        job_id = str(uuid.uuid4())[:8]

    specs = _resolve_specs(providers, query)
    if not specs:
        raise RuntimeError("No providers available after filtering.")

    actual_providers = [s.provider for s in specs]
    usage.create_job(job_id=job_id, query=query, providers=actual_providers, context=context)

    # Pre-flight visibility hook
    if verbose:
        print(f"\n[gather:{job_id}] query={query!r}", file=sys.stderr)
        for spec in specs:
            meta = PROVIDER_META.get(spec.provider, {})
            tier = meta.get("tier", "?")
            est = meta.get("est", "?")
            print(f"  → {spec.provider:<28} tier={tier:<10} est={est}", file=sys.stderr)
        print("", file=sys.stderr)

    def _worker(spec: WorkerSpec) -> dict:
        if _is_cdp(spec):
            return _run_cdp_worker(spec, query, job_id)
        else:
            return _run_api_worker(spec, query, job_id)

    # Fire workers in background thread so start_gather returns immediately
    def _run_all():
        with ThreadPoolExecutor(max_workers=len(specs)) as ex:
            futures: dict[Future, WorkerSpec] = {ex.submit(_worker, s): s for s in specs}
            for fut in as_completed(futures):
                spec = futures[fut]
                try:
                    result = fut.result()
                    if verbose:
                        status = result.get("status", "?")
                        elapsed = result.get("elapsed_ms", 0)
                        score = result.get("score")
                        score_str = f"  score={score:.2f}" if score is not None else ""
                        print(f"[gather:{job_id}] {spec.provider:<28} {status:<6} {elapsed}ms{score_str}",
                              file=sys.stderr)
                except Exception as e:
                    if verbose:
                        print(f"[gather:{job_id}] {spec.provider:<28} CRASH  {e}", file=sys.stderr)

        usage.finish_job(job_id)
        if verbose:
            print(f"[gather:{job_id}] all workers done", file=sys.stderr)

    import threading
    t = threading.Thread(target=_run_all, daemon=True)
    t.start()

    return job_id


def wait_for_job(job_id: str, poll_interval: float = 1.0, timeout: float = 1800.0):
    """Block until job status becomes 'done' or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = usage.get_job(job_id)
        if job and job.get("status") == "done":
            return
        time.sleep(poll_interval)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")

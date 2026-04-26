"""Integration agent — synthesize gathered results via claude -p opus-4-7."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import os
from typing import Optional

from power_search.tracker import usage


SYSTEM_PROMPT = """\
You are a research integration agent. You receive raw search results gathered in parallel \
from multiple providers (Perplexity, Gemini, ChatGPT, etc.) on a single query.

Your job:
1. Synthesize the results into a single coherent answer. Do not just concatenate — reconcile, \
   identify consensus, flag conflicting claims, and surface what the sources agree on vs. disagree on.
2. If some providers failed or timed out, note what's missing and whether it affects confidence.
3. Attribute key claims to their source provider.
4. If a Cortex problem context was provided (why this question is being asked, what decision it \
   informs), weight the synthesis toward what matters for that context.
5. End with a short "Confidence" note: high / medium / low, and why.

Be direct. No filler. The user is an expert — write for them.
"""


def _build_prompt(query: str, results: list[dict], context: Optional[str]) -> str:
    lines = [f"## Query\n{query}\n"]

    if context:
        lines.append(f"## Context (why we're asking)\n{context}\n")

    done = [r for r in results if r["status"] == "done"]
    failed = [r for r in results if r["status"] == "error"]

    lines.append(f"## Gathered results ({len(done)} succeeded, {len(failed)} failed)\n")

    for r in done:
        provider = r["provider"]
        elapsed = r.get("elapsed_ms", 0)
        score = r.get("score")
        score_str = f"  quality={score:.2f}" if score is not None else ""
        lines.append(f"### [{provider}]  ({elapsed}ms{score_str})")
        lines.append(r.get("content", "(empty)"))
        lines.append("")

    if failed:
        lines.append("## Failed / timed out providers")
        for r in failed:
            lines.append(f"- {r['provider']}: {r.get('error', 'unknown error')}")
        lines.append("")

    return "\n".join(lines)


def integrate(job_id: str, wait: bool = False, verbose: bool = True) -> str:
    """
    Run the integration agent over whatever results have landed for job_id.
    If wait=True, blocks until the job is done first.
    Returns the integrated text and writes it to the job store.
    """
    if wait:
        from power_search.gather import wait_for_job
        if verbose:
            print(f"[integrate:{job_id}] waiting for all workers...", file=sys.stderr)
        wait_for_job(job_id)

    job = usage.get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found.")

    results = usage.get_results(job_id)
    done = [r for r in results if r["status"] == "done"]
    failed = [r for r in results if r["status"] == "error"]

    if not done:
        raise RuntimeError(f"No successful results yet for job {job_id}. "
                           f"{len(failed)} workers failed.")

    if verbose:
        print(f"[integrate:{job_id}] integrating {len(done)} results "
              f"({len(failed)} failed)...", file=sys.stderr)

    prompt = _build_prompt(
        query=job["query"],
        results=results,
        context=job.get("context"),
    )

    # Write prompt to temp file to avoid shell quoting issues
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        cmd = [
            "claude", "-p",
            "--model", "claude-opus-4-7",
            "--system-prompt", SYSTEM_PROMPT,
            "--bare",
            prompt,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"claude -p failed (exit {proc.returncode}): {proc.stderr[:500]}")
        integrated = proc.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError("Integration agent timed out after 120s")
    finally:
        os.unlink(prompt_file)

    sources_used = [r["provider"] for r in done]
    sources_missing = [r["provider"] for r in failed]

    usage.write_integration(
        job_id=job_id,
        content=integrated,
        sources_used=sources_used,
        sources_missing=sources_missing,
    )

    if verbose:
        print(f"[integrate:{job_id}] done — {len(integrated)} chars", file=sys.stderr)

    # Commit to depot
    try:
        import sys as _sys
        _sys.path.insert(0, str(__import__("pathlib").Path.home() / "projects/agent-depot"))
        from depot import depot
        depot.commit(
            type="gather",
            title=f"{job['query'][:60]}",
            content=integrated,
            metadata={
                "job_id": job_id,
                "providers_used": sources_used,
                "providers_missing": sources_missing,
                "context": job.get("context") or "",
            },
            short_summary=(
                f"*[gather]* {job['query'][:60]}\n"
                f"Sources: {', '.join(sources_used)}\n"
                f"Missing: {', '.join(sources_missing) or 'none'}"
            ),
        )
    except Exception as e:
        print(f"[integrate:{job_id}] depot commit failed: {e}", file=sys.stderr)

    return integrated

"""CLI for the gather+integrate system — `power-search-gather`."""

from __future__ import annotations

import argparse
import json
import sys

from power_search.tracker import usage


def cmd_start(args):
    from power_search.gather import start_gather

    providers = [p.strip() for p in args.providers.split(",")] if args.providers else [
        "perplexity", "gemini_grounded",
    ]
    job_id = start_gather(
        query=args.query,
        providers=providers,
        context=args.context or None,
        verbose=True,
    )
    print(f"\njob_id: {job_id}")
    print(f"Gathering from: {', '.join(providers)}")
    print(f"Run `power-search-gather status {job_id}` to check progress.")
    print(f"Run `power-search-gather integrate {job_id}` when ready.")


def cmd_status(args):
    job = usage.get_job(args.job_id)
    if not job:
        print(f"Job {args.job_id} not found.", file=sys.stderr)
        sys.exit(1)

    results = usage.get_results(args.job_id)
    done = [r for r in results if r["status"] == "done"]
    failed = [r for r in results if r["status"] == "error"]
    pending_count = len(job["providers"]) - len(results)

    print(f"\nJob: {job['id']}  status={job['status']}")
    print(f"Query: {job['query']}")
    if job.get("context"):
        print(f"Context: {job['context']}")
    print(f"\nProviders: {len(done)} done  {len(failed)} failed  {max(0,pending_count)} pending\n")

    for r in results:
        status = r["status"]
        elapsed = r.get("elapsed_ms", 0)
        score = r.get("score")
        score_str = f"  score={score:.2f}" if score is not None else ""
        err = f"  error={r['error'][:60]}" if r.get("error") else ""
        print(f"  {r['provider']:<30} {status:<6}  {elapsed}ms{score_str}{err}")

    integrations = usage.get_integrations(args.job_id)
    if integrations:
        print(f"\nIntegrations: {len(integrations)}")
        for i, ig in enumerate(integrations, 1):
            print(f"  #{i}  {ig['created_at']}  sources={ig['sources_used']}")


def cmd_integrate(args):
    from power_search.integrate import integrate

    result = integrate(
        job_id=args.job_id,
        wait=args.wait,
        verbose=True,
    )
    print("\n" + "─" * 60)
    print(result)
    print("─" * 60)


def cmd_history(args):
    jobs = usage.list_jobs(limit=args.limit)
    if not jobs:
        print("No gather jobs found.")
        return

    print(f"\n{'ID':<10} {'Status':<10} {'Created':<26} {'Query'}")
    print("─" * 80)
    for j in jobs:
        query_preview = j["query"][:45] + "…" if len(j["query"]) > 45 else j["query"]
        print(f"{j['id']:<10} {j['status']:<10} {j['created_at'][:26]}  {query_preview}")


def main():
    parser = argparse.ArgumentParser(
        prog="power-search-gather",
        description="Parallel gather + Opus integration agent",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # start
    p_start = sub.add_parser("start", help="Start a gather job")
    p_start.add_argument("query", help="The research query")
    p_start.add_argument("--context", "-c", help="Cortex context: why we're asking, what decision this informs")
    p_start.add_argument("--providers", "-p",
                         help="Comma-separated provider list (default: perplexity,gemini_grounded). "
                              "CDP providers: chatgpt/instant, chatgpt/thinking, chatgpt/pro, "
                              "gemini_cdp/flash, gemini_cdp/thinking, gemini_cdp/pro")
    p_start.set_defaults(func=cmd_start)

    # status
    p_status = sub.add_parser("status", help="Show job status and landed results")
    p_status.add_argument("job_id")
    p_status.set_defaults(func=cmd_status)

    # integrate
    p_integrate = sub.add_parser("integrate", help="Run integration agent over landed results")
    p_integrate.add_argument("job_id")
    p_integrate.add_argument("--wait", action="store_true",
                              help="Block until all workers finish before integrating")
    p_integrate.set_defaults(func=cmd_integrate)

    # history
    p_history = sub.add_parser("history", help="List recent gather jobs")
    p_history.add_argument("--limit", type=int, default=20)
    p_history.set_defaults(func=cmd_history)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

"""CLI entry point for power-search."""

from __future__ import annotations

import argparse
import sys

from power_search.base import Intent
from power_search.router import search, BudgetExceededError, NoProviderError
from power_search.tracker import usage
from power_search.config import configure, ProviderKeyError


INTENT_MAP = {
    "search": Intent.SEARCH,
    "research": Intent.RESEARCH,
    "read": Intent.READ_URL,
    "scrape": Intent.SCRAPE_URL,
    "crawl": Intent.CRAWL_SITE,
    "youtube": Intent.YOUTUBE,
    "generate": Intent.GENERATE,
    "google": Intent.GROUNDED_SEARCH,
}


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="power-search",
        description="Unified search and AI router with cost tracking",
    )
    sub = parser.add_subparsers(dest="command")

    # Search command (default)
    search_p = sub.add_parser("query", aliases=list(INTENT_MAP.keys()), help="Run a search")
    search_p.add_argument("query", nargs="+", help="Search query or URL")
    search_p.add_argument("--provider", "-p", help="Force a specific provider")
    search_p.add_argument("--save", "-o", help="Write output to file instead of stdout")
    search_p.add_argument("--prefer", choices=["smart", "cheapest", "quality"], default=None)
    search_p.add_argument("--budget", type=float, default=None, help="Daily budget in USD")

    # Usage command
    usage_p = sub.add_parser("usage", help="Show usage and cost stats")
    usage_p.add_argument("--all", action="store_true", help="Show all-time stats")
    usage_p.add_argument("--recent", type=int, default=0, help="Show last N queries")
    usage_p.add_argument("--providers", action="store_true", help="Show cost by provider")

    args = parser.parse_args(argv)

    if args.command == "usage":
        _handle_usage(args)
        return

    if args.command is None:
        parser.print_help()
        return

    # Apply runtime config
    if args.prefer:
        configure(prefer=args.prefer)
    if args.budget:
        configure(daily_budget=args.budget)

    intent = INTENT_MAP.get(args.command)
    query_str = " ".join(args.query)

    try:
        result = search(query_str, intent=intent, provider=args.provider)
    except (BudgetExceededError, NoProviderError, ProviderKeyError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.save:
        with open(args.save, "w") as f:
            f.write(result.content)
        print(f"Saved to {args.save} [{result.provider}] ${result.cost:.4f}")
    else:
        print(f"[{result.provider}] (${result.cost:.4f}, {result.elapsed_ms}ms)")
        print()
        print(result.content)
        if result.sources:
            print("\n---\nSources:")
            for s in result.sources:
                print(f"  - {s}")


def _handle_usage(args):
    if args.recent > 0:
        for entry in usage.recent(args.recent):
            print(f"  {entry['ts'][:19]}  {entry['provider']:20s}  ${entry['cost']:.4f}  {entry['query'][:60]}")
        return

    if args.providers:
        for name, cost in usage.by_provider().items():
            print(f"  {name:20s}  ${cost:.4f}")
        return

    summary = usage.total() if args.all else usage.today()
    print(summary)


if __name__ == "__main__":
    main()

"""Power Search — Unified search and AI router with cost tracking."""

from power_search.base import SearchResult, Intent
from power_search.router import search, Router
from power_search.tracker import usage
from power_search.config import configure

__all__ = ["search", "SearchResult", "Intent", "Router", "usage", "configure"]
__version__ = "0.1.0"

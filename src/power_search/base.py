"""Core types shared across the package."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Intent(Enum):
    """What the user wants to do."""

    SEARCH = "search"  # web search for a query
    RESEARCH = "research"  # deep research with citations
    READ_URL = "read_url"  # extract content from a single URL
    SCRAPE_URL = "scrape_url"  # render + scrape a JS-heavy URL
    CRAWL_SITE = "crawl_site"  # multi-page site crawl
    YOUTUBE = "youtube"  # search YouTube videos
    YOUTUBE_VIDEO = "youtube_video"  # transcript/summary of a specific video
    GENERATE = "generate"  # text generation / coding
    GROUNDED_SEARCH = "grounded_search"  # Google-grounded AI search


@dataclass
class SearchResult:
    """Unified result from any provider."""

    content: str
    provider: str
    cost: float  # estimated USD
    intent: Intent
    query: str
    sources: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    elapsed_ms: int = 0
    metadata: dict = field(default_factory=dict)


class Provider(Protocol):
    """Interface every provider must satisfy."""

    name: str
    intents: list[Intent]

    def available(self) -> bool:
        """Return True if the provider's API key / deps are present."""
        ...

    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        """Execute a search/fetch and return a result with cost."""
        ...


def timed(fn):
    """Decorator that sets elapsed_ms on the returned SearchResult."""

    def wrapper(*args, **kwargs):
        start = time.monotonic()
        result = fn(*args, **kwargs)
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result

    return wrapper

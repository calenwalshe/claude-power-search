"""Smart router — detects intent, picks provider, enforces budget."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from power_search.base import Intent, SearchResult
from power_search.circuit_breaker import CircuitBreaker
from power_search.config import get_config, ProviderKeyError
from power_search.tracker import usage


# Intent detection patterns
URL_RE = re.compile(r"https?://\S+")
YOUTUBE_URL_RE = re.compile(r"(?:youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)")
YOUTUBE_RE = re.compile(r"youtube|youtubers?|video", re.I)
RESEARCH_RE = re.compile(
    r"research|citations?|cite|sources|latest|current events|recent news|deep dive",
    re.I,
)
SCRAPE_RE = re.compile(r"scrape|render|javascript|js.heavy", re.I)
CRAWL_RE = re.compile(r"crawl|index.*(site|pages)|all pages|full site", re.I)
GENERATE_RE = re.compile(r"generate|write a|draft a|create a|compose", re.I)
GOOGLE_RE = re.compile(r"google|grounded search|search with gemini", re.I)

# Provider preference order per intent (tries first available)
ROUTING_TABLE: dict[Intent, list[str]] = {
    Intent.SEARCH: ["gemini_grounded", "tavily", "perplexity"],
    Intent.RESEARCH: ["perplexity", "gemini_grounded", "gemini"],
    Intent.READ_URL: ["jina", "firecrawl"],
    Intent.SCRAPE_URL: ["firecrawl", "jina"],
    Intent.CRAWL_SITE: ["crawl4ai", "firecrawl"],
    Intent.YOUTUBE: ["gemini_youtube", "tavily"],
    Intent.YOUTUBE_VIDEO: ["gemini_youtube"],
    Intent.GENERATE: ["gemini", "openai"],
    Intent.GROUNDED_SEARCH: ["gemini_grounded"],
}

# Cheapest-first override
CHEAPEST_TABLE: dict[Intent, list[str]] = {
    Intent.SEARCH: ["gemini_grounded", "tavily", "perplexity"],
    Intent.RESEARCH: ["gemini_grounded", "perplexity", "gemini"],
    Intent.READ_URL: ["jina", "firecrawl"],
    Intent.SCRAPE_URL: ["jina", "firecrawl"],
    Intent.CRAWL_SITE: ["crawl4ai", "firecrawl"],
    Intent.YOUTUBE: ["gemini_youtube", "tavily"],
    Intent.YOUTUBE_VIDEO: ["gemini_youtube"],
    Intent.GENERATE: ["gemini", "openai"],
    Intent.GROUNDED_SEARCH: ["gemini_grounded"],
}

# Quality-first override
QUALITY_TABLE: dict[Intent, list[str]] = {
    Intent.SEARCH: ["perplexity", "gemini_grounded", "tavily"],
    Intent.RESEARCH: ["perplexity", "gemini", "gemini_grounded"],
    Intent.READ_URL: ["firecrawl", "jina"],
    Intent.SCRAPE_URL: ["firecrawl", "jina"],
    Intent.CRAWL_SITE: ["crawl4ai", "firecrawl"],
    Intent.YOUTUBE: ["gemini_youtube", "tavily"],
    Intent.YOUTUBE_VIDEO: ["gemini_youtube"],
    Intent.GENERATE: ["openai", "gemini"],
    Intent.GROUNDED_SEARCH: ["gemini_grounded"],
}


def detect_intent(query: str) -> Intent:
    """Detect what the user wants from the query string."""
    has_url = bool(URL_RE.search(query))

    # YouTube URL → direct video processing (before generic URL handling)
    if has_url and YOUTUBE_URL_RE.search(query):
        return Intent.YOUTUBE_VIDEO
    if has_url and CRAWL_RE.search(query):
        return Intent.CRAWL_SITE
    if has_url and SCRAPE_RE.search(query):
        return Intent.SCRAPE_URL
    if has_url:
        return Intent.READ_URL
    if YOUTUBE_RE.search(query):
        return Intent.YOUTUBE
    if GOOGLE_RE.search(query):
        return Intent.GROUNDED_SEARCH
    if RESEARCH_RE.search(query):
        return Intent.RESEARCH
    if GENERATE_RE.search(query):
        return Intent.GENERATE
    return Intent.SEARCH


class Router:
    def __init__(self):
        from power_search.providers import PROVIDER_MAP
        self._providers = PROVIDER_MAP
        self._breaker = CircuitBreaker()

    def search(
        self,
        query: str,
        intent: Intent | None = None,
        provider: str | None = None,
        **kwargs,
    ) -> SearchResult:
        """Route a query to the best available provider."""
        cfg = get_config()

        # Budget check
        if cfg.daily_budget is not None:
            spent = usage.today_cost()
            if spent >= cfg.daily_budget:
                raise BudgetExceededError(spent, cfg.daily_budget)

        if intent is None:
            intent = detect_intent(query)

        # Explicit provider override
        if provider:
            p = self._providers.get(provider)
            if not p:
                raise ValueError(f"Unknown provider: {provider}. Available: {list(self._providers.keys())}")
            result = p.search(query, intent, **kwargs)
            self._track(result)
            return result

        # Pick routing table based on preference
        if cfg.prefer == "cheapest":
            table = CHEAPEST_TABLE
        elif cfg.prefer == "quality":
            table = QUALITY_TABLE
        else:
            table = ROUTING_TABLE

        candidates = table.get(intent, ROUTING_TABLE.get(intent, []))

        # Filter to enabled providers if configured
        if cfg.enabled_providers:
            candidates = [c for c in candidates if c in cfg.enabled_providers]

        # Try each candidate in order
        last_error = None
        tried: list[str] = []
        for name in candidates:
            if not self._breaker.call_allowed(name):
                continue
            p = self._providers.get(name)
            if p is None or not p.available():
                continue
            tried.append(name)
            try:
                result = p.search(query, intent, **kwargs)
                self._breaker.record_success(name)
                self._track(result, candidates_tried=tried, fallback_count=len(tried) - 1)
                return result
            except ProviderKeyError:
                continue
            except Exception as e:
                self._breaker.record_failure(name)
                last_error = e
                continue

        # All candidates failed — record the error event
        error_provider = tried[-1] if tried else "none"
        usage.record_event(
            provider=error_provider,
            intent=intent.value,
            query=query,
            cost=0.0,
            outcome="error",
            candidates_tried=tried,
            fallback_count=max(0, len(tried) - 1),
            error_type=type(last_error).__name__ if last_error else "NoProviderError",
        )
        if last_error:
            raise last_error
        raise NoProviderError(intent)

    def _track(self, result: SearchResult,
               candidates_tried: list[str] | None = None,
               fallback_count: int = 0):
        usage.record_event(
            provider=result.provider,
            intent=result.intent.value,
            query=result.query,
            cost=result.cost,
            outcome="success",
            candidates_tried=candidates_tried or [result.provider],
            fallback_count=fallback_count,
            elapsed_ms=result.elapsed_ms,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
        )
        # Keep legacy usage table populated for budget checks
        usage.record(
            provider=result.provider,
            intent=result.intent.value,
            query=result.query,
            cost=result.cost,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            elapsed_ms=result.elapsed_ms,
        )


class BudgetExceededError(Exception):
    def __init__(self, spent: float, budget: float):
        super().__init__(f"Daily budget exceeded: ${spent:.2f} spent of ${budget:.2f} limit")


class NoProviderError(Exception):
    def __init__(self, intent: Intent):
        super().__init__(
            f"No available provider for intent '{intent.value}'. "
            f"Check API keys and installed dependencies."
        )


# Module-level convenience function
_router: Router | None = None


def search(
    query: str,
    intent: Intent | None = None,
    provider: str | None = None,
    **kwargs,
) -> SearchResult:
    """Search using the global router instance."""
    global _router
    if _router is None:
        _router = Router()
    return _router.search(query, intent=intent, provider=provider, **kwargs)

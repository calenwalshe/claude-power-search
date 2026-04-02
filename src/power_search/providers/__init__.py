"""Provider registry."""

from __future__ import annotations

from power_search.providers.tavily import TavilyProvider
from power_search.providers.jina import JinaProvider
from power_search.providers.firecrawl import FirecrawlProvider
from power_search.providers.crawl4ai_provider import Crawl4AIProvider
from power_search.providers.perplexity import PerplexityProvider
from power_search.providers.gemini import GeminiProvider, GeminiGroundedProvider
from power_search.providers.openai_provider import OpenAIProvider
from power_search.providers.youtube import GeminiYouTubeProvider

ALL_PROVIDERS: list = [
    TavilyProvider(),
    JinaProvider(),
    FirecrawlProvider(),
    Crawl4AIProvider(),
    PerplexityProvider(),
    GeminiProvider(),
    GeminiGroundedProvider(),
    GeminiYouTubeProvider(),
    OpenAIProvider(),
]

PROVIDER_MAP: dict[str, object] = {p.name: p for p in ALL_PROVIDERS}

__all__ = ["ALL_PROVIDERS", "PROVIDER_MAP"]

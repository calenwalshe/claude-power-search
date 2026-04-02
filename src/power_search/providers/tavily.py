"""Tavily Search provider."""

from __future__ import annotations

from power_search.base import Intent, SearchResult, timed
from power_search.config import get_config


# Tavily pricing: ~$0.008/basic query, ~$0.016/advanced query
COST_BASIC = 0.008
COST_ADVANCED = 0.016


class TavilyProvider:
    name = "tavily"
    intents = [Intent.SEARCH, Intent.YOUTUBE]

    def available(self) -> bool:
        return get_config().get_key("TAVILY_API_KEY") is not None

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        from tavily import TavilyClient

        api_key = get_config().require_key("TAVILY_API_KEY")
        client = TavilyClient(api_key=api_key)

        search_kwargs = {
            "query": query,
            "search_depth": kwargs.get("depth", "advanced"),
            "max_results": kwargs.get("max_results", 7),
            "include_raw_content": True,
        }

        if intent == Intent.YOUTUBE:
            search_kwargs["include_domains"] = ["youtube.com"]
            search_kwargs["max_results"] = kwargs.get("max_results", 5)
            search_kwargs["include_raw_content"] = False

        results = client.search(**search_kwargs)

        lines = []
        sources = []
        for r in results.get("results", []):
            lines.append(f"## {r.get('title', '')}\n{r.get('url', '')}\n{r.get('content', '')}\n")
            sources.append(r.get("url", ""))

        depth = search_kwargs["search_depth"]
        cost = COST_ADVANCED if depth == "advanced" else COST_BASIC

        return SearchResult(
            content="\n".join(lines),
            provider=self.name,
            cost=cost,
            intent=intent,
            query=query,
            sources=sources,
        )

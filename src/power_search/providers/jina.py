"""Jina Reader provider — free URL-to-markdown extraction."""

from __future__ import annotations

import requests

from power_search.base import Intent, SearchResult, timed


# Jina is free for 10M tokens. Negligible cost.
COST_PER_PAGE = 0.0001


class JinaProvider:
    name = "jina"
    intents = [Intent.READ_URL]

    def available(self) -> bool:
        return True  # No API key required

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        url = query  # For Jina, the "query" is the URL
        resp = requests.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/markdown"},
            timeout=30,
        )
        resp.raise_for_status()

        return SearchResult(
            content=resp.text,
            provider=self.name,
            cost=COST_PER_PAGE,
            intent=intent,
            query=query,
            sources=[url],
        )

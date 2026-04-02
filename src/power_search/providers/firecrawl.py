"""Firecrawl provider — JS-rendered scraping."""

from __future__ import annotations

import requests

from power_search.base import Intent, SearchResult, timed
from power_search.config import get_config


# ~$0.005/page on Hobby plan
COST_PER_PAGE = 0.005


class FirecrawlProvider:
    name = "firecrawl"
    intents = [Intent.SCRAPE_URL]

    def available(self) -> bool:
        return get_config().get_key("FIRECRAWL_API_KEY") is not None

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        api_key = get_config().require_key("FIRECRAWL_API_KEY")
        url = query

        resp = requests.post(
            "https://api.firecrawl.dev/v1/scrape",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"url": url, "formats": ["markdown"]},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("data", {}).get("markdown", "")

        return SearchResult(
            content=content,
            provider=self.name,
            cost=COST_PER_PAGE,
            intent=intent,
            query=query,
            sources=[url],
        )

"""Crawl4AI provider — local multi-page crawling (free)."""

from __future__ import annotations

from power_search.base import Intent, SearchResult, timed


class Crawl4AIProvider:
    name = "crawl4ai"
    intents = [Intent.CRAWL_SITE]

    def available(self) -> bool:
        try:
            import crawl4ai  # noqa: F401
            return True
        except ImportError:
            return False

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        import asyncio
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        url = query

        async def _crawl():
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(url=url, config=CrawlerRunConfig())
                return result.markdown

        content = asyncio.run(_crawl())

        return SearchResult(
            content=content,
            provider=self.name,
            cost=0.0,  # Local — free
            intent=intent,
            query=query,
            sources=[url],
        )

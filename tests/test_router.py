"""Tests for intent detection and routing logic."""

import pytest

from power_search.base import Intent
from power_search.router import detect_intent


class TestDetectIntent:
    def test_url_defaults_to_read(self):
        assert detect_intent("https://example.com/article") == Intent.READ_URL

    def test_url_with_scrape_keyword(self):
        assert detect_intent("scrape https://example.com") == Intent.SCRAPE_URL

    def test_url_with_crawl_keyword(self):
        assert detect_intent("crawl https://example.com") == Intent.CRAWL_SITE

    def test_youtube_keyword(self):
        assert detect_intent("search youtube for rust tutorials") == Intent.YOUTUBE

    def test_research_keyword(self):
        assert detect_intent("research quantum computing with citations") == Intent.RESEARCH

    def test_google_keyword(self):
        assert detect_intent("google this topic") == Intent.GROUNDED_SEARCH

    def test_generate_keyword(self):
        assert detect_intent("write a poem about cats") == Intent.GENERATE

    def test_plain_query_defaults_to_search(self):
        assert detect_intent("best restaurants in Toronto") == Intent.SEARCH

    def test_latest_news(self):
        assert detect_intent("what's the latest on AI regulation") == Intent.RESEARCH

    def test_deep_research(self):
        assert detect_intent("deep research into climate models") == Intent.RESEARCH

    def test_grounded_search_gemini(self):
        assert detect_intent("search with Gemini for recipes") == Intent.GROUNDED_SEARCH

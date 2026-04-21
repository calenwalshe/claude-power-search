"""Tests for AdaptiveRouter — memory-informed provider reordering."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from power_search.base import Intent, SearchResult
from power_search.adaptive import AdaptiveRouter


def make_stats(provider: str, intent: str, total: int, success: int, avg_latency_ms: float) -> dict:
    return {
        "provider": provider,
        "intent": intent,
        "total": total,
        "success": success,
        "success_rate": success / total if total else 0.0,
        "avg_latency_ms": avg_latency_ms,
        "avg_fallback_count": 0.0,
        "total_cost": 0.0,
    }


def make_result(provider: str) -> SearchResult:
    return SearchResult(
        content="result content here that is long enough",
        provider=provider,
        cost=0.01,
        intent=Intent.SEARCH,
        query="test query",
        sources=["http://example.com"],
    )


class TestReorderCandidates:
    def test_reorder_by_success_rate(self):
        router = AdaptiveRouter()
        stats = [
            make_stats("tavily", "search", 10, 6, 200.0),
            make_stats("perplexity", "search", 10, 9, 300.0),
        ]
        with patch.object(router._tracker, "route_stats", return_value=stats):
            result = router.reorder_candidates(["tavily", "perplexity"], "search")
        assert result[0] == "perplexity"
        assert result[1] == "tavily"

    def test_low_sample_providers_keep_position(self):
        router = AdaptiveRouter()
        stats = [
            make_stats("tavily", "search", 4, 1, 100.0),
            make_stats("perplexity", "search", 10, 9, 300.0),
        ]
        with patch.object(router._tracker, "route_stats", return_value=stats):
            result = router.reorder_candidates(["tavily", "perplexity"], "search")
        assert result[0] == "tavily"

    def test_zero_success_rate_moves_to_end(self):
        router = AdaptiveRouter()
        stats = [
            make_stats("tavily", "search", 10, 0, 100.0),
            make_stats("perplexity", "search", 10, 8, 200.0),
            make_stats("gemini_grounded", "search", 10, 5, 150.0),
        ]
        with patch.object(router._tracker, "route_stats", return_value=stats):
            result = router.reorder_candidates(["tavily", "perplexity", "gemini_grounded"], "search")
        assert result[-1] == "tavily"

    def test_reorder_noop_when_no_stats(self):
        router = AdaptiveRouter()
        with patch.object(router._tracker, "route_stats", return_value=[]):
            result = router.reorder_candidates(["tavily", "perplexity", "gemini_grounded"], "search")
        assert result == ["tavily", "perplexity", "gemini_grounded"]

    def test_adaptive_search_uses_reordered_candidates(self):
        router = AdaptiveRouter()
        stats = [
            make_stats("tavily", "search", 10, 2, 200.0),
            make_stats("perplexity", "search", 10, 9, 300.0),
        ]
        call_order = []

        def mock_search_perplexity(query, intent, **kwargs):
            call_order.append("perplexity")
            return make_result("perplexity")

        def mock_search_tavily(query, intent, **kwargs):
            call_order.append("tavily")
            return make_result("tavily")

        mock_perplexity = MagicMock()
        mock_perplexity.available.return_value = True
        mock_perplexity.search.side_effect = mock_search_perplexity

        mock_tavily = MagicMock()
        mock_tavily.available.return_value = True
        mock_tavily.search.side_effect = mock_search_tavily

        with patch.object(router._tracker, "route_stats", return_value=stats):
            with patch.object(router._router, "_providers", {"perplexity": mock_perplexity, "tavily": mock_tavily}):
                router.search("test query", intent=Intent.SEARCH, _candidates=["tavily", "perplexity"])

        assert call_order[0] == "perplexity"

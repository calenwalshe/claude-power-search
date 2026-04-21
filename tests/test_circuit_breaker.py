"""Tests for CircuitBreaker and its integration with Router."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from power_search.base import Intent, SearchResult
from power_search.circuit_breaker import CircuitBreaker


def make_result(provider: str = "tavily") -> SearchResult:
    return SearchResult(
        content="result content here that is long enough",
        provider=provider,
        cost=0.01,
        intent=Intent.SEARCH,
        query="test query",
        sources=["http://example.com"],
    )


class TestCircuitBreaker:
    def test_initially_closed(self):
        cb = CircuitBreaker()
        assert cb.call_allowed("tavily") is True
        assert cb.state("tavily") == "closed"

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        assert cb.call_allowed("tavily") is True
        cb.record_failure("tavily")
        assert cb.call_allowed("tavily") is False
        assert cb.state("tavily") == "open"

    def test_success_resets_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        cb.record_success("tavily")
        assert cb.state("tavily") == "closed"
        cb.record_failure("tavily")
        assert cb.call_allowed("tavily") is True

    def test_half_open_after_cooldown(self):
        clock = [0.0]

        def mock_time():
            return clock[0]

        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60, clock=mock_time)
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        assert cb.state("tavily") == "open"
        assert cb.call_allowed("tavily") is False

        clock[0] = 61.0
        assert cb.state("tavily") == "half_open"
        assert cb.call_allowed("tavily") is True

    def test_closes_on_success_from_half_open(self):
        clock = [0.0]

        def mock_time():
            return clock[0]

        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60, clock=mock_time)
        cb.record_failure("tavily")
        cb.record_failure("tavily")
        cb.record_failure("tavily")

        clock[0] = 61.0
        assert cb.state("tavily") == "half_open"

        cb.record_success("tavily")
        assert cb.state("tavily") == "closed"
        assert cb.call_allowed("tavily") is True

    def test_router_skips_open_circuit_provider(self):
        from power_search.router import Router
        from power_search.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("tavily")
        assert cb.state("tavily") == "open"

        mock_tavily = MagicMock()
        mock_tavily.available.return_value = True
        mock_tavily.search.return_value = make_result("tavily")

        mock_perplexity = MagicMock()
        mock_perplexity.available.return_value = True
        mock_perplexity.search.return_value = make_result("perplexity")

        router = Router()
        router._breaker = cb
        router._providers = {"tavily": mock_tavily, "perplexity": mock_perplexity}

        with patch("power_search.router.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.daily_budget = None
            cfg.prefer = "default"
            cfg.enabled_providers = None
            mock_cfg.return_value = cfg

            with patch("power_search.router.ROUTING_TABLE", {Intent.SEARCH: ["tavily", "perplexity"]}):
                result = router.search("test query", intent=Intent.SEARCH)

        mock_tavily.search.assert_not_called()
        mock_perplexity.search.assert_called_once()
        assert result.provider == "perplexity"

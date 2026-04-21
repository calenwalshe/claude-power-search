"""Tests for the adversarial critique module."""

from __future__ import annotations

import pytest

from power_search.base import Intent, SearchResult
from power_search.critic import critique, CritiqueResult


def make_result(
    content: str = "This is a sufficiently long result content for testing purposes.",
    provider: str = "tavily",
    intent: Intent = Intent.SEARCH,
    sources: list[str] | None = None,
    cost: float = 0.01,
) -> SearchResult:
    return SearchResult(
        content=content,
        provider=provider,
        cost=cost,
        intent=intent,
        query="test query",
        sources=sources if sources is not None else ["http://example.com"],
    )


class TestCritique:
    def test_good_result_passes(self):
        result = make_result(
            content="This is a comprehensive and well-written result that covers the topic in depth. "
                    "It includes multiple sentences with varied content and is definitely long enough "
                    "to satisfy the minimum length requirement for a quality search result.",
            sources=["http://example.com", "http://other.com"],
        )
        cr = critique(result)
        assert isinstance(cr, CritiqueResult)
        assert cr.passed is True
        assert cr.score >= 0.8

    def test_short_result_flagged(self):
        result = make_result(content="Too short.")
        cr = critique(result)
        assert "too_short" in cr.flags

    def test_no_sources_flagged_for_research(self):
        result = make_result(
            content="This is a sufficiently long result content for testing purposes that has many words.",
            intent=Intent.RESEARCH,
            sources=[],
        )
        cr = critique(result)
        assert "no_sources" in cr.flags

    def test_repetitive_content_flagged(self):
        sentence = "The quick brown fox jumps over the lazy dog."
        content = " ".join([sentence] * 5)
        result = make_result(content=content)
        cr = critique(result)
        assert "repetitive" in cr.flags

    def test_expensive_result_flagged(self):
        result = make_result(
            content="This is a sufficiently long result content for testing purposes that has many words.",
            cost=0.15,
        )
        cr = critique(result)
        assert "expensive" in cr.flags

    def test_score_is_fraction_of_passed_checks(self):
        result = make_result(content="Too short.", cost=0.01)
        cr = critique(result)
        assert "too_short" in cr.flags
        num_flags = len(cr.flags)
        total_checks = 5
        expected_score = (total_checks - num_flags) / total_checks
        assert abs(cr.score - expected_score) < 0.01

    def test_critique_result_has_provider_and_query(self):
        result = make_result(provider="perplexity")
        cr = critique(result)
        assert cr.provider == "perplexity"
        assert cr.query == "test query"

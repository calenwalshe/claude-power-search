"""Tests for cost tracking."""

import tempfile
from pathlib import Path

from power_search.config import configure
from power_search.tracker import Tracker


def test_record_and_query():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        configure(db_path=db_path)

        tracker = Tracker()
        tracker.record(
            provider="tavily",
            intent="search",
            query="test query",
            cost=0.016,
            tokens_in=0,
            tokens_out=0,
            elapsed_ms=250,
        )
        tracker.record(
            provider="perplexity",
            intent="research",
            query="another query",
            cost=0.025,
            tokens_in=100,
            tokens_out=500,
            elapsed_ms=1200,
        )

        summary = tracker.today()
        assert summary.total_queries == 2
        assert abs(summary.total_cost - 0.041) < 0.001
        assert "tavily" in summary.by_provider
        assert "perplexity" in summary.by_provider

        recent = tracker.recent(5)
        assert len(recent) == 2
        assert recent[0]["provider"] == "perplexity"  # most recent first


def test_by_provider():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        configure(db_path=db_path)

        tracker = Tracker()
        tracker.record("tavily", "search", "q1", 0.008)
        tracker.record("tavily", "search", "q2", 0.016)
        tracker.record("jina", "read_url", "q3", 0.0001)

        providers = tracker.by_provider()
        assert abs(providers["tavily"] - 0.024) < 0.001
        assert abs(providers["jina"] - 0.0001) < 0.0001

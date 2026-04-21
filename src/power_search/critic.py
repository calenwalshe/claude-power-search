"""Adversarial critique — rule-based quality scoring for search results."""

from __future__ import annotations

from dataclasses import dataclass, field

from power_search.base import Intent, SearchResult

_RESEARCH_INTENTS = {Intent.RESEARCH, Intent.SEARCH}
_COST_THRESHOLD = 0.10
_MIN_LENGTH = 100
_REPETITION_THRESHOLD = 0.40
_PASS_THRESHOLD = 0.6


@dataclass
class CritiqueResult:
    passed: bool
    score: float
    flags: list[str]
    provider: str
    query: str


def critique(result: SearchResult) -> CritiqueResult:
    """Score a search result on quality dimensions."""
    flags: list[str] = []
    total_checks = 5

    if len(result.content) < _MIN_LENGTH:
        flags.append("too_short")

    if result.intent in _RESEARCH_INTENTS and not result.sources:
        flags.append("no_sources")

    if _is_repetitive(result.content):
        flags.append("repetitive")

    if result.cost > _COST_THRESHOLD:
        flags.append("expensive")

    score = (total_checks - len(flags)) / total_checks
    return CritiqueResult(
        passed=score >= _PASS_THRESHOLD,
        score=round(score, 4),
        flags=flags,
        provider=result.provider,
        query=result.query,
    )


def _is_repetitive(content: str) -> bool:
    sentences = [s.strip() for s in content.split(".") if s.strip()]
    if len(sentences) < 2:
        return False
    unique = set(sentences)
    duplicate_ratio = 1.0 - (len(unique) / len(sentences))
    return duplicate_ratio > _REPETITION_THRESHOLD

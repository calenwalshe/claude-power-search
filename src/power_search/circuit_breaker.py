"""Circuit breaker — prevents hammering a failing provider."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class _ProviderState:
    failures: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: int = 60,
        clock: Callable[[], float] | None = None,
    ):
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock or time.monotonic
        self._states: dict[str, _ProviderState] = {}

    def _get(self, provider: str) -> _ProviderState:
        if provider not in self._states:
            self._states[provider] = _ProviderState()
        return self._states[provider]

    def state(self, provider: str) -> str:
        s = self._get(provider)
        if s.opened_at is None:
            return "closed"
        if self._clock() - s.opened_at >= self._cooldown:
            return "half_open"
        return "open"

    def call_allowed(self, provider: str) -> bool:
        st = self.state(provider)
        return st in ("closed", "half_open")

    def record_success(self, provider: str):
        s = self._get(provider)
        s.failures = 0
        s.opened_at = None

    def record_failure(self, provider: str):
        s = self._get(provider)
        s.failures += 1
        if s.failures >= self._threshold and s.opened_at is None:
            s.opened_at = self._clock()

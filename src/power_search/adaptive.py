"""Memory-informed routing — reorders provider candidates using historical stats."""

from __future__ import annotations

from power_search.base import Intent, SearchResult
from power_search.tracker import Tracker, usage as _default_usage

MIN_SAMPLES = 5


class AdaptiveRouter:
    """Wraps Router with route_stats-informed provider reordering."""

    def __init__(self, tracker: Tracker | None = None):
        from power_search.router import Router
        self._router = Router()
        self._tracker = tracker or _default_usage

    def reorder_candidates(self, candidates: list[str], intent: str) -> list[str]:
        """Reorder candidates by success_rate DESC, avg_latency_ms ASC.

        Providers with < MIN_SAMPLES events keep their original position.
        Providers with success_rate == 0.0 move to end.
        Returns reordered list.
        """
        stats = self._tracker.route_stats(intent=intent)
        stat_map = {s["provider"]: s for s in stats}

        eligible = []
        ineligible_positions: dict[int, str] = {}

        for i, name in enumerate(candidates):
            s = stat_map.get(name)
            if s is None or s["total"] < MIN_SAMPLES:
                ineligible_positions[i] = name
            else:
                eligible.append(name)

        def sort_key(name: str):
            s = stat_map[name]
            zero_rate = 1 if s["success_rate"] == 0.0 else 0
            return (zero_rate, -s["success_rate"], s["avg_latency_ms"])

        eligible.sort(key=sort_key)

        result = list(candidates)
        eligible_iter = iter(eligible)
        for i in range(len(result)):
            if i not in ineligible_positions:
                result[i] = next(eligible_iter)

        return result

    def search(
        self,
        query: str,
        intent: Intent | None = None,
        provider: str | None = None,
        _candidates: list[str] | None = None,
        **kwargs,
    ) -> SearchResult:
        """Like Router.search but candidates are reordered by historical performance."""
        from power_search.router import detect_intent, ROUTING_TABLE, CHEAPEST_TABLE, QUALITY_TABLE
        from power_search.config import get_config

        if intent is None:
            intent = detect_intent(query)

        if _candidates is not None:
            candidates = self.reorder_candidates(_candidates, intent.value)
        else:
            cfg = get_config()
            if cfg.prefer == "cheapest":
                table = CHEAPEST_TABLE
            elif cfg.prefer == "quality":
                table = QUALITY_TABLE
            else:
                table = ROUTING_TABLE
            raw = table.get(intent, ROUTING_TABLE.get(intent, []))
            candidates = self.reorder_candidates(raw, intent.value)

        providers = self._router._providers
        last_error = None
        tried: list[str] = []
        for name in candidates:
            p = providers.get(name)
            if p is None or not p.available():
                continue
            tried.append(name)
            try:
                result = p.search(query, intent, **kwargs)
                self._router._track(result, candidates_tried=tried, fallback_count=len(tried) - 1)
                return result
            except Exception as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        from power_search.router import NoProviderError
        raise NoProviderError(intent)

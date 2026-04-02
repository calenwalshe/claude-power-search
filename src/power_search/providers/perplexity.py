"""Perplexity provider — deep research with citations."""

from __future__ import annotations

import requests

from power_search.base import Intent, SearchResult, timed
from power_search.config import get_config


# Sonar Pro: ~$3/1M in, ~$15/1M out + $0.006-0.014/request
# Rough estimate per typical query
COST_PER_QUERY = 0.02


class PerplexityProvider:
    name = "perplexity"
    intents = [Intent.RESEARCH, Intent.SEARCH]

    def available(self) -> bool:
        return get_config().get_key("PPLX_API_KEY") is not None

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        api_key = get_config().require_key("PPLX_API_KEY")
        model = kwargs.get("model", "sonar-pro")
        max_tokens = kwargs.get("max_tokens", 4000)

        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": query}],
                "max_tokens": max_tokens,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage_data = data.get("usage", {})
        tokens_in = usage_data.get("prompt_tokens", 0)
        tokens_out = usage_data.get("completion_tokens", 0)

        # More accurate cost from actual token counts
        cost = (tokens_in * 3 / 1_000_000) + (tokens_out * 15 / 1_000_000) + 0.008

        sources = []
        citations = data["choices"][0]["message"].get("citations", [])
        if isinstance(citations, list):
            sources = citations

        return SearchResult(
            content=content,
            provider=self.name,
            cost=cost,
            intent=intent,
            query=query,
            sources=sources,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

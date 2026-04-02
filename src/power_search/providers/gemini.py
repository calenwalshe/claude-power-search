"""Gemini providers — standard and grounded search."""

from __future__ import annotations

import requests

from power_search.base import Intent, SearchResult, timed
from power_search.config import get_config


# Gemini 2.5 Flash: $0.30/1M in, $2.50/1M out
# Grounded search: $0.035/query after 1,500 free/day
COST_FLASH_PER_QUERY = 0.001  # typical short query
COST_GROUNDED_PER_QUERY = 0.036  # after free quota


class GeminiProvider:
    name = "gemini"
    intents = [Intent.GENERATE, Intent.RESEARCH]

    def available(self) -> bool:
        return get_config().get_key("GEMINI_API_KEY") is not None

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        api_key = get_config().require_key("GEMINI_API_KEY")
        model = kwargs.get("model", "gemini-2.5-flash")

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": query}]}]},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage_data = data.get("usageMetadata", {})
        tokens_in = usage_data.get("promptTokenCount", 0)
        tokens_out = usage_data.get("candidatesTokenCount", 0)
        cost = (tokens_in * 0.30 / 1_000_000) + (tokens_out * 2.50 / 1_000_000)

        return SearchResult(
            content=content,
            provider=self.name,
            cost=cost,
            intent=intent,
            query=query,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


class GeminiGroundedProvider:
    name = "gemini_grounded"
    intents = [Intent.GROUNDED_SEARCH, Intent.SEARCH]

    def available(self) -> bool:
        return get_config().get_key("GEMINI_API_KEY") is not None

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        api_key = get_config().require_key("GEMINI_API_KEY")
        model = kwargs.get("model", "gemini-2.5-flash")

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": query}]}],
                "tools": [{"google_search": {}}],
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        parts = data["candidates"][0]["content"]["parts"]
        text_parts = [p["text"] for p in parts if "text" in p]
        content = "\n".join(text_parts)

        # Extract grounding sources
        sources = []
        grounding = data["candidates"][0].get("groundingMetadata", {})
        for chunk in grounding.get("groundingChunks", []):
            web = chunk.get("web", {})
            if web:
                uri = web.get("uri", "")
                title = web.get("title", "")
                sources.append(f"{title} — {uri}" if title else uri)

        usage_data = data.get("usageMetadata", {})
        tokens_in = usage_data.get("promptTokenCount", 0)
        tokens_out = usage_data.get("candidatesTokenCount", 0)
        token_cost = (tokens_in * 0.30 / 1_000_000) + (tokens_out * 2.50 / 1_000_000)
        cost = token_cost + COST_GROUNDED_PER_QUERY  # conservative: assume past free quota

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

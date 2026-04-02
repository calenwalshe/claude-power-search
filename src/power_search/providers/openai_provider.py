"""OpenAI GPT provider."""

from __future__ import annotations

from power_search.base import Intent, SearchResult, timed
from power_search.config import get_config


# GPT-4o: $2.50/1M in, $10/1M out
COST_IN_PER_M = 2.50
COST_OUT_PER_M = 10.00


class OpenAIProvider:
    name = "openai"
    intents = [Intent.GENERATE]

    def available(self) -> bool:
        return get_config().get_key("OPENAI_API_KEY") is not None

    @timed
    def search(self, query: str, intent: Intent, **kwargs) -> SearchResult:
        from openai import OpenAI

        api_key = get_config().require_key("OPENAI_API_KEY")
        model = kwargs.get("model", "gpt-4o")

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": query}],
        )

        content = response.choices[0].message.content
        tokens_in = response.usage.prompt_tokens if response.usage else 0
        tokens_out = response.usage.completion_tokens if response.usage else 0
        cost = (tokens_in * COST_IN_PER_M / 1_000_000) + (tokens_out * COST_OUT_PER_M / 1_000_000)

        return SearchResult(
            content=content,
            provider=self.name,
            cost=cost,
            intent=intent,
            query=query,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

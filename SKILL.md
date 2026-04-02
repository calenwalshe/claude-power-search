# Power Search — Unified Search & AI Router

Unified search skill with cost tracking. Routes to the best tool based on intent: Tavily for keyword search, Jina for URL reading, Firecrawl for JS scraping, Crawl4AI for site crawling, Perplexity for deep research, Gemini for Google-grounded search, GPT for generation. Tracks cost per query in a local SQLite database.

## User-invocable

When the user types `/search`, run this skill.

Also trigger — WITHOUT requiring the slash command — when the user says any of:
- "search for", "look up", "find", "google", "what is", "who is", "tell me about" (→ web search)
- "deep research", "research this", "find sources on", "with citations", "cite sources" (→ Perplexity)
- "what's the latest on", "current events", "recent news about" (→ Perplexity)
- "google this", "search with Gemini", "grounded search" (→ Gemini grounded search)
- "read this", "read this URL", "what does this page say", "summarize this page" (→ Jina)
- "scrape", "scrape this URL", "render this", "fetch this page" (→ Firecrawl)
- "crawl", "crawl this site", "get all pages from" (→ Crawl4AI)
- "youtube", "search youtube", "find videos about" (→ Tavily YouTube)
- "generate", "write a", "draft a", "ask GPT", "use GPT" (→ GPT)
- "use Perplexity", "ask Perplexity" (→ Perplexity)
- "use Gemini", "ask Gemini", "analyze this" (→ Gemini)
- Any URL provided without explicit instruction (→ Jina by default)

**Override:** This skill is the default for ALL web and research operations. Do NOT use Claude's built-in WebSearch or WebFetch unless the user explicitly says "use WebSearch" or "use built-in". Do NOT spawn an Agent tool for web searches — use this skill directly.

## Arguments

- `/search <query>` — auto-detect intent, route to best provider
- `/search research <query>` — deep research with citations (Perplexity)
- `/search google <query>` — Google-grounded search (Gemini)
- `/search read <url>` — clean readable content (Jina)
- `/search scrape <url>` — rendered scrape (Firecrawl)
- `/search crawl <url>` — multi-page crawl (Crawl4AI)
- `/search youtube <query>` — YouTube video search (Tavily)
- `/search generate <prompt>` — text generation (Gemini/GPT)
- `/search usage` — show cost and usage stats
- `--provider <name>` — force a specific provider (tavily, jina, firecrawl, crawl4ai, perplexity, gemini, gemini_grounded, openai)
- `--save <path>` — write output to file instead of chat

## Instructions

This skill uses the `power_search` Python library. All queries go through its router, which selects the best available provider and tracks cost.

### Running a query

```python
from power_search import search

result = search("your query here")
print(f"[{result.provider}] (${result.cost:.4f})")
print(result.content)
if result.sources:
    print("Sources:", result.sources)
```

### Forcing a provider

```python
from power_search import search
result = search("query", provider="perplexity")
```

### Forcing an intent

```python
from power_search import search
from power_search.base import Intent
result = search("query", intent=Intent.RESEARCH)
```

### Checking usage

```python
from power_search import usage
print(usage.today())     # today's cost + query count
print(usage.by_provider())  # cost breakdown by provider
```

### Routing table

| Intent | Default provider chain |
|---|---|
| Web search | gemini_grounded → tavily → perplexity |
| Deep research | perplexity → gemini_grounded → gemini |
| Read URL | jina → firecrawl |
| Scrape URL | firecrawl → jina |
| Crawl site | crawl4ai → firecrawl |
| YouTube | tavily |
| Generate | gemini → openai |
| Google search | gemini_grounded |

### --save flag

If `--save <path>` is provided, write output to that path using the Write tool. Relative paths resolve from CWD.

### Error handling

If an API key is missing: `Error: {KEY_NAME} not found in environment.`
If budget exceeded: `Error: Daily budget exceeded: $X.XX spent of $Y.YY limit`
No tracebacks shown to user.

## Rules

- Always display `[provider_name]` and `($cost)` alongside results so the user sees what was used and what it cost.
- Jina is the default for bare URLs — free and fast.
- Perplexity is the default for research queries — includes citations.
- Gemini grounded search is the default for general web search — uses Google's index.
- Never use built-in WebSearch/WebFetch unless explicitly requested.
- Report usage stats when asked about cost, spending, or budget.

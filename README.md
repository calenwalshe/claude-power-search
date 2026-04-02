# Power Search

Unified search and AI router with cost tracking. One interface for 7 search/AI providers, with automatic routing and per-query cost logging.

## Providers

| Provider | What it does | Cost | API key |
|----------|-------------|------|---------|
| **Tavily** | Web search (keywords, questions) | ~$0.008-0.016/query | `TAVILY_API_KEY` |
| **Jina Reader** | URL → clean markdown | Free (10M tokens) | None |
| **Firecrawl** | JS-rendered page scraping | ~$0.005/page | `FIRECRAWL_API_KEY` |
| **Crawl4AI** | Multi-page site crawling | Free (local) | None |
| **Perplexity** | Deep research with citations | ~$0.01-0.03/query | `PPLX_API_KEY` |
| **Gemini** | AI analysis + generation | ~$0.001/query | `GEMINI_API_KEY` |
| **Gemini Grounded** | Google Search + AI synthesis | ~$0.036/query (1,500 free/day) | `GEMINI_API_KEY` |
| **OpenAI GPT-4o** | Text generation, coding | ~$0.01-0.05/query | `OPENAI_API_KEY` |

## Install

```bash
pip install power-search

# Optional: for full-site crawling
pip install "power-search[crawl]"
```

## Setup

Set API keys as environment variables:

```bash
export TAVILY_API_KEY=tvly-...
export FIRECRAWL_API_KEY=fc-...
export PPLX_API_KEY=pplx-...
export GEMINI_API_KEY=AI...
export OPENAI_API_KEY=sk-...
```

Only configure the providers you want to use. The router skips unavailable providers.

## Usage

### Python

```python
from power_search import search, usage, configure

# Auto-routed search (picks best available provider)
result = search("what are the latest developments in Rust async")
print(result.content)       # the answer
print(result.provider)      # "gemini_grounded"
print(result.cost)          # 0.036
print(result.sources)       # ["https://...", ...]

# Force a specific provider
result = search("explain quantum computing", provider="perplexity")

# Read a URL
result = search("https://example.com/article")

# Check spending
print(usage.today())         # $0.42 across 38 queries
print(usage.by_provider())   # {"tavily": 0.12, "perplexity": 0.30}

# Set a daily budget
configure(daily_budget=5.00)

# Prefer cheapest providers
configure(prefer="cheapest")
```

### CLI

```bash
# Auto-routed
power-search search "latest rust async developments"

# Specific intent
power-search research "quantum computing breakthroughs 2026"
power-search read https://example.com/article
power-search scrape https://js-heavy-site.com
power-search youtube "rust async tutorials"
power-search google "current weather in Toronto"

# Force provider
power-search search "query" --provider perplexity

# Save to file
power-search research "topic" --save output.md

# Check usage
power-search usage
power-search usage --recent 10
power-search usage --providers
```

### Claude Code Skill

Install as a Claude Code skill:

```bash
claude skill install https://github.com/calenwalshe/claude-power-search
```

Then use `/search` in any Claude Code session.

## Routing

The router detects intent from your query and picks the best available provider:

| You say | Intent | Provider |
|---------|--------|----------|
| "search for X" | Search | Gemini Grounded → Tavily |
| "research X with citations" | Research | Perplexity → Gemini Grounded |
| `https://example.com` | Read URL | Jina → Firecrawl |
| "scrape this JS page" | Scrape | Firecrawl → Jina |
| "crawl the whole site" | Crawl | Crawl4AI → Firecrawl |
| "search youtube for X" | YouTube | Tavily |
| "google this" | Grounded Search | Gemini Grounded |
| "write a draft of X" | Generate | Gemini → GPT-4o |

Preference modes (`configure(prefer=...)`):
- `"smart"` (default) — best tool for the job
- `"cheapest"` — minimizes cost
- `"quality"` — maximizes result quality

## Cost Tracking

Every query is logged to `~/.power-search/usage.db` (SQLite) with:
- Timestamp, provider, intent, query text
- Estimated cost in USD
- Token counts (where available)
- Response time in ms

## License

MIT

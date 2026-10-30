---
name: news-sentiment
description: Get recent news and sentiment for a stock. Use when user asks about news, headlines, sentiment, what's happening with a stock, or recent developments.
dependencies: ["trading-skills"]
---

# News Sentiment

Fetch recent news from Yahoo Finance: yfinance's ticker news first, then Yahoo's per-ticker RSS feed when that comes back empty or fails.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/news.py SYMBOL [--limit LIMIT]
```

## Arguments

- `SYMBOL` - Ticker symbol
- `--limit` - Number of articles (default: 10)

## Output

Returns JSON with:
- `articles` - Array of recent news with title, publisher, date (`YYYY-MM-DD HH:MM ET`), link, type
- `count` - Number of articles returned
- `source` - `"yfinance"` or `"yahoo-rss"`
- `note` - With `yahoo-rss`: items are tagged to the ticker, not necessarily about it, and arrive newest first. `publisher` is the link's host (often `finance.yahoo.com`), since the feed carries no publisher
- `message: "No news found"` - both sources answered with no articles
- `error` - no articles and at least one source failed; never read this as "no news"

Present key headlines and note any significant news that could impact the stock. Judge the sentiment from the headlines yourself. With `yahoo-rss`, skip market-wide stories that are not about the company when assessing its sentiment.

## Dependencies

- `yfinance`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
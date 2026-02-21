---
name: news-sentiment
description: Get recent news and sentiment for a stock. Use when user asks about news, headlines, sentiment, what's happening with a stock, or recent developments.
dependencies: ["trading-skills"]
---

# News Sentiment

Fetch recent news from Yahoo Finance.

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
- `articles` - Array of recent news with title, publisher, date, link
- `summary` - Brief summary of overall sentiment

Present key headlines and note any significant news that could impact the stock.

## Dependencies

- `yfinance`

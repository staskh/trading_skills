---
name: price-history
description: Get historical price data (OHLCV) for a stock. Use when user asks about price history, historical data, past performance, price over time, or needs data for chart analysis.
dependencies: ["trading-skills"]
---

# Price History

Fetch historical OHLCV data from Yahoo Finance.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/history.py SYMBOL [--period PERIOD] [--interval INTERVAL]
```

## Arguments

- `SYMBOL` - Ticker symbol
- `--period` - Time period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max (default: 1mo)
- `--interval` - Data interval: 1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo (default: 1d)

## Output

Returns JSON with:
- `symbol` - Ticker
- `period` - Requested period
- `interval` - Data interval
- `data` - Array of {date, open, high, low, close, volume}

Summarize key price movements, highs/lows, and trends.

## Dependencies

- `yfinance`

---
name: stock-quote
description: Get real-time stock quote with price, volume, change, market cap, and 52-week range for any ticker symbol. Use when user asks about current stock price, quote, or basic stock info.
dependencies: ["trading-skills"]
---

# Stock Quote

Fetch current stock data from Yahoo Finance.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

Run the quote script with the ticker symbol:

```bash
uv run python scripts/quote.py SYMBOL
```

Replace SYMBOL with the requested ticker (e.g., AAPL, MSFT, TSLA, SPY).

## Output

The script outputs JSON with:
- symbol, name, price, change, change_percent
- volume, avg_volume, market_cap
- high_52w, low_52w, pe_ratio, dividend_yield

Present the data in a readable format. Highlight significant moves (>2% change).

## Dependencies

- `yfinance`

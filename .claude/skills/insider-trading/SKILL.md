---
name: insider-trading
description: Get insider trading activity (SEC Form 4 filings) for one or more stocks. Use when user asks about insider buying/selling, executive transactions, insider sentiment, or Form 4 activity.
dependencies: ["trading-skills"]
---

# Insider Trading

Fetch recent insider transactions from Yahoo Finance (SEC Form 4 data).

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/insider_trading.py SYMBOLS [--days DAYS]
```

## Arguments

- `SYMBOLS` - Single ticker or comma-separated list (e.g., `NVDA` or `NVDA,PLTR,GOOG`)
- `--days` - Trailing days to look back (default: 90)

## Output

Returns JSON with:
- `transactions` - List of insider trades with insider name, role, transaction type, shares, price, value, date, ownership type
- `summary` - Net sentiment (`net_buying`, `net_selling`, `neutral`), buy/sell counts and values

For multiple symbols, results are ranked by net buying value (most buying first).

## Use Cases

- *"Show me insider buys for NVDA in the last 90 days"*
- *"Compare insider activity across NVDA, PLTR, GOOG"*
- *"Which of these stocks has the most insider selling recently?"*

## Dependencies

- `yfinance`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
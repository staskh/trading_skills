---
name: option-chain
description: Get option chain data including calls and puts with strikes, bids, asks, volume, open interest, and implied volatility. Use when user asks about options, option prices, calls, puts, or option chain for a specific expiration date.
dependencies: ["trading-skills"]
---

# Option Chain

Fetch option chain data from Yahoo Finance for a specific expiration date.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

First, get available expiration dates:
```bash
uv run python scripts/options.py SYMBOL --expiries
```

Then fetch the chain for a specific expiry:
```bash
uv run python scripts/options.py SYMBOL --expiry YYYY-MM-DD
```

## Arguments

- `SYMBOL` - Ticker symbol (e.g., AAPL, SPY, TSLA)
- `--expiries` - List available expiration dates only
- `--expiry YYYY-MM-DD` - Fetch chain for specific date

## Output

Returns JSON with:
- `calls` - Array of call options with strike, bid, ask, volume, openInterest, impliedVolatility
- `puts` - Array of put options with same fields
- `underlying_price` - Current stock price for reference

Present data as a table. Highlight high volume/OI strikes and notable IV levels.

## Dependencies

- `pandas`
- `yfinance`

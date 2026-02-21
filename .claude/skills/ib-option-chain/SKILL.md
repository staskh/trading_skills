---
name: ib-option-chain
description: Get option chain data from Interactive Brokers including calls and puts with strikes, bids, asks, volume, and implied volatility. Use when user asks about options using IBKR data, or needs real-time option quotes from their broker. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Option Chain

Fetch option chain data from Interactive Brokers for a specific expiration date.

## Prerequisites

User must have TWS or IB Gateway running locally with API enabled:
- Paper trading: port 7497
- Live trading: port 7496

## Instructions

First, get available expiration dates:
```bash
uv run python scripts/options.py SYMBOL --expiries
```

Then fetch the chain for a specific expiry:
```bash
uv run python scripts/options.py SYMBOL --expiry YYYYMMDD
```

## Arguments

- `SYMBOL` - Ticker symbol (e.g., AAPL, SPY, TSLA)
- `--expiries` - List available expiration dates only
- `--expiry YYYYMMDD` - Fetch chain for specific date (IB format: YYYYMMDD, no dashes)
- `--port` - IB port (default: 7496 for live trading)

## Output

Returns JSON with:
- `calls` - Array of call options with strike, bid, ask, lastPrice, volume, openInterest, impliedVolatility
- `puts` - Array of put options with same fields
- `underlying_price` - Current stock price for reference
- `source` - "ibkr"

Present data as a table. Highlight high volume strikes and notable IV levels.

## Dependencies

- `ib-async`

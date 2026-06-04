---
name: ib-option-chain
description: Get option chain data from Interactive Brokers for equities, ETFs, and futures (FOP), including calls and puts with strikes, bids, asks, volume, implied volatility, and model Greeks. Use when user asks about options using IBKR data, futures options (NQ/ES/CL/GC...), or needs real-time option quotes from their broker. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Option Chain

Fetch option chain data from Interactive Brokers for a specific expiration date.
Handles **equities/ETFs** (Stock/OPT) and **futures options** (FOP) — the asset type is
detected automatically from the symbol (e.g. `NQ`, `ES`, `CL`, `GC` are treated as
futures with FOP options on their correct exchange and contract multiplier).

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

- `SYMBOL` - Ticker symbol. Equity/ETF (e.g., AAPL, SPY, TSLA) or futures root (e.g., NQ, ES, CL, GC) — futures are auto-detected and use FOP contracts.
- `--expiries` - List available expiration dates only
- `--expiry YYYYMMDD` - Fetch chain for specific date (IB format: YYYYMMDD, no dashes)
- `--port` - IB port (default: 7496 for live trading)

## Output

Returns JSON with:
- `calls` - Array of call options with strike, bid, ask, lastPrice, volume, openInterest, impliedVolatility, `greeks` (delta/gamma/theta/vega/iv from IB model), and `multiplier` (futures only)
- `puts` - Array of put options with same fields
- `underlying_price` - Current underlying price for reference (stock/ETF price or continuous-future price)
- `asset_type` - "stock" or "future"
- `source` - "ibkr"

For futures, only expiries up to the front continuous-future's expiry are returned; longer-dated FOPs require the next quarter's future. Futures quote nearly 24h on Globex, so Greeks populate pre-market.

Present data as a table. Highlight high volume strikes and notable IV levels.

## Dependencies

- `ib-async`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
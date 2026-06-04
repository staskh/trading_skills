---
name: ib-option-chain
description: Get option chain data from Interactive Brokers for equities, ETFs, and futures (FOP), including calls and puts with strikes, bids, asks, volume, implied volatility, and model Greeks. Use when user asks about options using IBKR data, futures options (NQ/ES/CL/GC...), or needs real-time option quotes from their broker. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Option Chain

Fetch option chain data from Interactive Brokers for a specific expiration date.
Handles **equities/ETFs** (Stock/OPT) and **futures options** (FOP). The asset type and
exchange are resolved from **IB contract details** (no hardcoded symbol table): auto-detect
tries a SMART stock first and falls back to a future when no stock exists (so `NQ`, `GC`,
`RTY` resolve as futures, while `AAPL` resolves as a stock even though it has an obscure
single-stock future). Tickers that are **both** a stock and a futures root (e.g. `ES`=Eversource,
`CL`=Colgate) default to the equity — pass `--sec-type fut` to force the future.

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

- `SYMBOL` - Ticker symbol. Equity/ETF (e.g., AAPL, SPY, TSLA) or futures root (e.g., NQ, ES, CL, GC) — asset type is auto-detected via IB.
- `--sec-type {stk,fut}` - Force the asset type. Default: auto-detect (stock-first). Use `fut` for ambiguous roots like ES/CL when you mean the future.
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
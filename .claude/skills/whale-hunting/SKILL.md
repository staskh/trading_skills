---
name: whale-hunting
description: Detect institutional whale activity in options for a given underlying. Use when the user asks about unusual options activity, large block trades, whale trades, or institutional options flow for a specific symbol.
dependencies: ["trading-skills"]
---

# Whale Hunting

Scans option chains for a given underlying to identify institutional-sized trades using a two-step approach:
1. **Crude scan** (Yahoo Finance) — finds contracts with anomalous daily investment vs the rest of the chain.
2. **Precise drill-down** (Massive API) — fetches per-second bars for each candidate and flags seconds with outlier dollar invested. Minimum whale order is $50k per transaction; in thin contracts (fewer than 10 traded seconds in the day) any second averaging more than $50k per transaction is a whale.

The scan always covers a two-session window: the latest trading session plus the one before it. During market hours that means today so far plus the full previous day. Past dates are not supported because Yahoo option chains are a live snapshot.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py SYMBOL [--months N] [--sigma-z F] [--summary]
```

## Arguments

- `SYMBOL` — Underlying ticker (e.g. `AAPL`, `NVDA`, `SPY`)
- `--months` — Max months until option expiration to consider (default: 2)
- `--sigma-z` — Modified Z-Score threshold for outlier detection in both the crude scan and the per-second drill-down (default: 3.5)
- `--summary` — Also compute per-ticker summary and include it in the JSON output

## Output

Returns JSON with:
- `underlying` — The scanned symbol
- `trading_date` — Latest trading session
- `window_dates` — `[previous session, latest session]`; all totals cover both
- `source` — `"massive"` (per-second data) or `"yahoo"` (daily chain data fallback)
- `total_whales` — Total whale events found
- `failed_fetches` — Per-second drill-down requests (one per contract per session) that errored; each is logged to stderr
- `total_call_invested` — Sum of invested dollars in call whale events
- `total_put_invested` — Sum of invested dollars in put whale events
- `call_put_ratio` — Call invested / put invested (null if no puts)
- `put_call_ratio` — Put invested / call invested (null if no calls)
- `whale_call_wall` / `whale_put_wall` — `{strike, invested}`: the strike with the most whale dollars per side (null if none)
- `open_interest` — Positioning from every fetched chain (expiries up to `--months`), not only whale contracts:
  - `call_oi`, `put_oi`, `put_call_oi_ratio` (null if no call OI)
  - `call_wall` / `put_wall` — `{strike, open_interest}`: the strike with the most open interest per side, summed across expiries (null if none)
- `directional_call_invested` — Call invested where break-even is ≥ 1.5% above spot
- `directional_put_invested` — Put invested where break-even is ≥ 1.5% below spot
- `directional_call_put_ratio` — Directional call / directional put invested (null if no directional puts)
- `whales` — List of whale events:
  - `timestamp`, `ticker`, `type`, `strike`, `spot` (underlying price at trade time), `expiry`
  - `close`, `volume`, `transactions`, `invested`, `break_even`, `pct_from_spot` (break-even distance from spot, %)
  - Missing values (e.g. `spot` for a trade before the first underlying bar) are `null`
- `summary` *(present only when `--summary` is passed)* — List of per-ticker aggregates:
  - `ticker`, `type`, `strike`, `expiry`, `whale_count`, `total_invested`, `break_even`

## Examples

```bash
# Hunt whales for AAPL (latest and previous trading sessions)
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py AAPL

# With per-ticker summary
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py HOOD --months 3 --summary

# Looser detection threshold
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py SPY --sigma-z 2.0
```

## Reporting

After running the script, present the results as follows.

**Header line:**
> Whale activity for **{underlying}** on {window_dates[0]} – {window_dates[1]} — source: {source}
> Call flow: ${total_call_invested:,.0f} | Put flow: ${total_put_invested:,.0f} | C/P ratio: {call_put_ratio:.2f}
> Directional (≥1.5% B/E from spot) — Calls: ${directional_call_invested:,.0f} | Puts: ${directional_put_invested:,.0f} | C/P ratio: {directional_call_put_ratio:.2f}
> Open interest — P/C ratio: {open_interest.put_call_oi_ratio:.2f} | Call wall: {open_interest.call_wall.strike} | Put wall: {open_interest.put_wall.strike}

Print `—` for any null ratio or wall.

**When `--summary` was requested**, render the `summary` array as a table:

| Time (ET) | Ticker | Type | Strike | Expiry | # Events | Total Invested | Break Even |
|-----------|--------|------|--------|--------|----------|----------------|------------|
| {timestamp} | {ticker} | {type} | {strike} | {expiry} | {whale_count} | ${total_invested:,.0f} | {break_even} |

Sort by `total_invested` descending. For multi-event rows use the time range of first–last event (e.g. `11:46–12:33`).

**Interpretation guidance:**
- `source: "massive"` — High-confidence; per-second block trade data from Massive API
- `source: "yahoo"` — Fallback; daily-level data from Yahoo chains (Massive API key missing, or the drill-down found no whales). No `spot`/`pct_from_spot`, so directional totals are 0
- Judge direction by `directional_call_put_ratio`, not `call_put_ratio` — trades with break-even within 1.5% of spot (deep ITM stock replacement, hedges) carry no directional signal
- Low directional C/P ratio (< 0.5) — Bearish institutional positioning
- High directional C/P ratio (> 2.0) — Bullish institutional positioning
- OI call wall often acts as resistance and put wall as support into expiry; P/C OI > 1 leans defensive
- `transactions: 1` — Single block trade; strongest whale signal
- `failed_fetches > 0` — Totals may be understated; mention the count alongside the header line

## Requirements

- `MASSIVE_API_KEY` environment variable for per-second data. Without it, falls back to Yahoo Finance daily data (`source: "yahoo"`). An invalid key or a plan without 1-second aggregates is an error, not a fallback.


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
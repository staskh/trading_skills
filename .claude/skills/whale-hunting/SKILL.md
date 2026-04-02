---
name: whale-hunting
description: Detect institutional whale activity in options for a given underlying. Use when the user asks about unusual options activity, large block trades, whale trades, or institutional options flow for a specific symbol.
dependencies: ["trading-skills"]
---

# Whale Hunting

Scans option chains for a given underlying to identify institutional-sized trades using a two-step approach:
1. **Crude scan** (Yahoo Finance) — finds contracts with anomalous daily investment vs the rest of the chain.
2. **Precise drill-down** (Massive API) — fetches per-second bars for each candidate and flags seconds with outlier dollar invested.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py SYMBOL [--months N] [--date YYYY-MM-DD] [--sigma F] [--sigma-z F] [--summary]
```

## Arguments

- `SYMBOL` — Underlying ticker (e.g. `AAPL`, `NVDA`, `SPY`)
- `--months` — Max months until option expiration to consider (default: 2)
- `--date` — Trading date to analyze in `YYYY-MM-DD` format (default: latest trading day)
- `--sigma` — Std-deviation multiplier for crude outlier threshold (default: 3.0)
- `--sigma-z` — Modified Z-Score threshold for per-second small-sample detection (default: 3.5)
- `--summary` — Also compute per-ticker summary and include it in the JSON output

## Output

Returns JSON with:
- `underlying` — The scanned symbol
- `trading_date` — Date analyzed
- `source` — `"massive"` (per-second data) or `"yahoo only"` (daily chain data)
- `total_whales` — Total whale events found
- `total_call_invested` — Sum of invested dollars in call whale events
- `total_put_invested` — Sum of invested dollars in put whale events
- `call_put_ratio` — Call invested / put invested (null if no puts)
- `whales` — List of whale events:
  - `timestamp`, `ticker`, `type`, `strike`, `expiry`
  - `close`, `volume`, `transactions`, `invested`, `break_even`
- `summary` *(present only when `--summary` is passed)* — List of per-ticker aggregates:
  - `ticker`, `type`, `strike`, `expiry`, `whale_count`, `total_invested`, `break_even`

## Examples

```bash
# Hunt whales for AAPL (latest trading day)
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py AAPL

# Hunt whales for NVDA on a specific date
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py NVDA --date 2026-03-13

# With per-ticker summary
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py HOOD --months 3 --summary

# Looser detection threshold
uv run python .claude/skills/whale-hunting/scripts/whale_hunting.py SPY --sigma 2.0
```

## Reporting

After running the script, present the results as follows.

**Header line:**
> Whale activity for **{underlying}** on {trading_date} — source: {source}
> Call flow: ${total_call_invested:,.0f} | Put flow: ${total_put_invested:,.0f} | C/P ratio: {call_put_ratio:.2f}

**When `--summary` was requested**, render the `summary` array as a table:

| Time (ET) | Ticker | Type | Strike | Expiry | # Events | Total Invested | Break Even |
|-----------|--------|------|--------|--------|----------|----------------|------------|
| {timestamp} | {ticker} | {type} | {strike} | {expiry} | {whale_count} | ${total_invested:,.0f} | {break_even} |

Sort by `total_invested` descending. For multi-event rows use the time range of first–last event (e.g. `11:46–12:33`).

**Interpretation guidance:**
- `source: "massive"` — High-confidence; per-second block trade data from Massive API
- `source: "yahoo only"` — Fallback; daily-level data (Massive API key missing or no intraday data)
- Low C/P ratio (< 0.5) — Bearish institutional positioning
- High C/P ratio (> 2.0) — Bullish institutional positioning
- `transactions: 1` — Single block trade; strongest whale signal

## Requirements

- `MASSIVE_API_KEY` environment variable for per-second data. Without it, falls back to Yahoo Finance daily data.

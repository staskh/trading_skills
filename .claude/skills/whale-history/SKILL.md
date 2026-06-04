---
name: whale-history
description: Detect historical institutional whale options activity over a date range (weeks/months) for one underlying, using Massive OPRA day-aggregate flatfiles. Use when the user asks about whale trades, unusual options activity, or institutional flow OVER A PAST PERIOD (e.g. "last 2 months", "since April") rather than a single day. For a single latest-day scan use the whale-hunting skill instead.
dependencies: ["trading-skills"]
---

# Whale History

Scans **Massive OPRA `day_aggs` flatfiles** (S3) to find institutional-sized option
trades for an underlying across a date range. Unlike the live `whale-hunting` skill —
which is limited to the latest trading day and needs the REST `MASSIVE_API_KEY` 1-second
entitlement — this skill reads finalized end-of-day flatfiles, so it works over **weeks or
months of real history**.

For each trading day it computes dollar invested per contract
(`close × volume × 100`) and flags per-day outliers via a modified z-score plus an absolute
dollar floor.

## Credentials

Requires the Massive **flatfile (S3)** credentials in the environment / `.env`
(separate from the REST `MASSIVE_API_KEY`):

```
MASSIVE_S3_ACCESS_KEY_ID=...
MASSIVE_S3_SECRET_ACCESS_KEY=...
# optional overrides:
MASSIVE_S3_ENDPOINT=https://files.massive.com
MASSIVE_S3_BUCKET=flatfiles
```

## Usage

```bash
uv run python .claude/skills/whale-history/scripts/whale_history.py SYMBOL \
  [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--months N] \
  [--sigma-z F] [--floor DOLLARS] [--exclude-0dte] [--out PATH]
```

## Arguments

- `SYMBOL` — Underlying ticker (e.g. `SPY`, `NVDA`)
- `--start` / `--end` — Explicit date range. `--end` defaults to the latest session.
- `--months` — Lookback months when `--start` is omitted (default: 2)
- `--sigma-z` — Modified z-score threshold for outlier detection (default: 3.5)
- `--floor` — Minimum dollar invested to qualify as a whale (default: 500000)
- `--exclude-0dte` — Drop contracts expiring on the trade date (filters intraday 0DTE flow)
- `--out` — Also write the JSON to this path (use `sandbox/` per project convention)

## Output

JSON with: `underlying`, `source`, `start`, `end`, `trading_days`, `total_whales`,
`total_call_invested`, `total_put_invested`, `call_put_ratio`, `by_day` (per-day whale
counts), and `top_whales` (top 40 events with `date`, `ticker`, `type`, `strike`, `expiry`,
`close`, `volume`, `transactions`, `invested`, `mod_z`, `break_even`). Plus `generated_at`
and `data_delay`.

## Caveats

- `day_aggs` aggregates per contract per day, so a "whale" is a contract with anomalous
  **daily** dollar volume — not a single block trade. For true per-trade blocks use the
  OPRA `trades_v1` flatfiles (much larger files).
- 0DTE contracts dominate raw results for liquid names like SPY; pass `--exclude-0dte` to
  focus on multi-day directional bets.

## Examples

```bash
# SPY whales over the last 2 months
uv run python .claude/skills/whale-history/scripts/whale_history.py SPY --months 2 \
  --out sandbox/SPY_whale_history.json

# NVDA, explicit range, excluding 0DTE, higher floor
uv run python .claude/skills/whale-history/scripts/whale_history.py NVDA \
  --start 2026-04-01 --end 2026-06-03 --exclude-0dte --floor 1000000
```

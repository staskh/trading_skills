---
name: earnings-calendar
description: Get upcoming earnings dates with timing (before/after market) and EPS estimates. Use when user asks about earnings dates, earnings calendar, when a company reports, or upcoming earnings.
dependencies: ["trading-skills"]
---

# Earnings Calendar

Retrieve upcoming earnings dates for stocks.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/earnings.py SYMBOLS
```

## Arguments

- `SYMBOLS` - Ticker symbol or comma-separated list (e.g., `AAPL` or `AAPL,MSFT,GOOGL,NVDA`)

## Output

Single symbol returns:
- `symbol` - Ticker symbol
- `earnings_date` - Next earnings date (YYYY-MM-DD)
- `earnings_date_source` - Where the date came from: `yfinance` (primary), `nasdaq`, or `sec_estimate` (projected from SEC filing cadence)
- `timing` - "BMO" (Before Market Open), "AMC" (After Market Close), or null
- `eps_estimate` - Consensus EPS estimate, or null if unavailable

Multiple symbols returns:
- `results` - Array of earnings info, sorted by date (soonest first)

## Fallback data chain

The primary source is yfinance (Yahoo). When Yahoo returns no date (rate-limited
or blocked), the date is resolved through a fallback chain so the skill keeps
working — see `src/trading_skills/data_sources/`:

1. **yfinance** (primary) — date + timing + EPS estimate.
2. **NASDAQ** (`api.nasdaq.com`) — best-effort next date; also exposes EPS
   estimate/actual/surprise history (`resolve_earnings_surprises`).
3. **SEC EDGAR** (`data.sec.gov`) — official historical earnings-release dates
   (8-K Item 2.02); the next date is projected from the reporting cadence
   (`earnings_date_source: sec_estimate`).

The provenance is always surfaced in `earnings_date_source`, so an estimated date
is never presented as a confirmed one. Note: post-earnings price-move statistics
still require yfinance price history (no free fallback source).

## Examples

```bash
# Single symbol
uv run python scripts/earnings.py NVDA

# Multiple symbols (sorted by date)
uv run python scripts/earnings.py AAPL,MSFT,GOOGL,NVDA,META

# Portfolio earnings calendar
uv run python scripts/earnings.py CAT,GOOG,HOOD,IWM,NVDA,PLTR,QQQ,UNH
```

## Use Cases

- Check when positions have upcoming earnings risk
- Plan trades around earnings announcements
- Build an earnings calendar for watchlist

## Dependencies

- `pandas`
- `yfinance`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
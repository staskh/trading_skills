---
name: earnings-calendar
description: Get upcoming earnings dates with timing (before/after market) and EPS estimates. Use when user asks about earnings dates, earnings calendar, when a company reports, or upcoming earnings.
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
- `timing` - "BMO" (Before Market Open), "AMC" (After Market Close), or null
- `eps_estimate` - Consensus EPS estimate, or null if unavailable

Multiple symbols returns:
- `results` - Array of earnings info, sorted by date (soonest first)

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

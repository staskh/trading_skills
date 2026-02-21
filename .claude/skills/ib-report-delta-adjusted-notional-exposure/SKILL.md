---
name: ib-report-delta-adjusted-notional-exposure
description: Report delta-adjusted notional exposure across all IBKR accounts. Calculates option deltas using Black-Scholes and reports long/short exposure by account and underlying. Use when user asks about delta exposure, portfolio risk, or directional exposure.
---

# IB Delta-Adjusted Notional Exposure Report

Calculate and report delta-adjusted notional exposure across all Interactive Brokers accounts.

## Prerequisites

User must have TWS or IB Gateway running locally with API enabled:
- Paper trading: port 7497
- Live/Production trading: port 7496

## Instructions

### Step 1: Gather Data

```bash
uv run python scripts/delta_exposure.py [--port PORT]
```

The script returns JSON to stdout with all position deltas and summary data.

### Step 2: Format Report

Read `templates/markdown-template.md` for formatting instructions. Generate a markdown report from the JSON data and save to `sandbox/`.

**Filename**: `delta_exposure_report_{YYYYMMDD}_{HHMMSS}.md`

### Step 3: Report Results

Present the summary table (total long, short, net) and top exposures to the user. Include the saved report path.

## Arguments

- `--port` - IB port (default: 7497 for paper trading, use 7496 for production)

## JSON Output

Returns delta-adjusted notional exposure with:
- `connected` - Boolean
- `accounts` - List of account IDs
- `position_count` - Total positions
- `positions` - Array of positions with symbol, delta, delta_notional, spot price
- `summary` - Totals for long, short, and net delta notional
  - `by_account` - Long/short breakdown by account
  - `by_underlying` - Long/short/net breakdown by symbol

## Methodology

- **Equity Options**: Delta calculated via Black-Scholes with estimated IV based on moneyness
- **Futures**: Delta = 1.0 (full notional exposure)
- **Futures Options**: Delta calculated with lower IV assumption (20%)
- **Stocks**: Delta = 1.0

Delta-adjusted notional = delta x spot price x quantity x multiplier

## Examples

```bash
# Paper trading (default port 7497)
uv run python scripts/delta_exposure.py

# Production/Live trading (port 7496)
uv run python scripts/delta_exposure.py --port 7496
```

---
name: ib-report-delta-adjusted-notional-exposure
description: Report delta-adjusted notional exposure across all IBKR accounts. Calculates option deltas using Black-Scholes and reports long/short exposure by account and underlying. Use when user asks about delta exposure, portfolio risk, or directional exposure.
dependencies: ["trading-skills"]
---

# IB Delta-Adjusted Notional Exposure Report

Calculate and report delta-adjusted notional exposure across all Interactive Brokers accounts.

## IB Connection

TWS or IB Gateway must be running locally with API enabled:
- **Paper trading** — port 7497
- **Live trading** — port 7496
- **`IB_PORT` env var** — default port when `--port` is omitted (e.g. `IB_PORT=4001` for a Gateway container). Precedence: `--port` flag > `IB_PORT` > built-in default. Set it in the shell or a `.env` file.

**Port fallback:** If the configured port fails, automatically retry on the other port.
If the retry succeeds, save to memory which account type worked (live/paper) and reuse it for all IB skill calls in this and future sessions — until the user explicitly asks for the other account.
If both ports fail, ask the user to verify that TWS or IB Gateway is running with API access enabled.

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

- `--port` - IB port (default: 7497 for paper trading)

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
# Paper trading (default)
uv run python scripts/delta_exposure.py

# Live trading
uv run python scripts/delta_exposure.py --port 7496
```


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
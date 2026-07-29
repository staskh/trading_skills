---
name: ib-portfolio-action-report
description: Generate a comprehensive portfolio action report with earnings dates and risk assessment. Use when user asks for portfolio review, action items, earnings risk, or position management across IB accounts. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Portfolio Action Report

Generate a comprehensive portfolio action report that analyzes all positions across Interactive Brokers accounts, fetches earnings dates, and provides traffic-light risk indicators (🔴🟡🟢) for each position.

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

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/report.py [--port PORT] [--account ACCOUNT]
```

The script returns JSON to stdout with analyzed portfolio data including risk levels, earnings dates, technical indicators, and spread groupings.

### Step 2: Format Report

Read `templates/markdown-template.md` for formatting instructions. Generate a markdown report from the JSON data and save to `sandbox/`.

**Filename**: `ib_portfolio_action_report_{ACCOUNT}_{YYYY-MM-DD}_{HHmm}.md`

### Step 3: Report Results

Present critical findings to the user: red/yellow items requiring attention, top priority actions, and the saved report path.

## Arguments

- `--port` - IB port (default: 7497 for paper trading)
- `--account` - Specific account ID to analyze (optional, defaults to all accounts)

## JSON Output

The script returns structured JSON with:
- `generated_at` - NY timestamp (e.g. `"2026-04-29 19:35 ET"`)
- `data_delay` - Data freshness (`"real-time"`)
- `accounts` - List of account IDs
- `summary` - Red/yellow/green counts
- `spreads` - All positions grouped into spreads with risk level, urgency, and recommendations
- `technicals` - Technical indicators per symbol (RSI, trend, SMAs, MACD, ADX)
- `earnings` - Earnings dates per symbol
- `prices` - Current prices per symbol
- `earnings_calendar` - Upcoming earnings with account/position info
- `account_summary` - Position and risk counts per account

## Report Sections

1. **Critical Summary**: Count of positions by risk level (🔴/🟡/🟢)
2. **Immediate Action Required**: Positions expiring within 2 days
3. **Urgent - Expiring Within 1 Week**: Short-term positions needing attention
4. **Critical Earnings Alert**: Positions with earnings this week
5. **Earnings Next Week**: Upcoming earnings exposure
6. **Expiring in 2 Weeks**: Medium-term expirations
7. **Longer-Dated Positions**: Core holdings with spread analysis
8. **Top Priority Actions**: Numbered action items by urgency
9. **Position Size Summary**: Account-level breakdown
10. **Earnings Calendar**: Next 30 days of earnings dates
11. **Technical Analysis Summary**: RSI, trend, SMAs, MACD, ADX for each underlying

## Example Usage

```bash
# All accounts (paper, default)
uv run python scripts/report.py

# Live account
uv run python scripts/report.py --port 7496

# Specific account
uv run python scripts/report.py --account U790497
```

## Dependencies

- `ib-async`
- `pandas-ta`
- `yfinance`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
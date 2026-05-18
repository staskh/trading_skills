---
name: ib-trades-history
description: Fetch trade executions from Interactive Brokers filtered by account, date range, or symbol. Supports live API (~7 days history) and FlexReport (full history). Use when user asks about their trades, executions, or transaction history. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Trades History

Fetch trade executions from Interactive Brokers.

## Prerequisites

User must have TWS or IB Gateway running locally with API enabled:
- Paper trading: port 7497
- Live trading: port 7496

For full trade history beyond ~7 days, the user needs a Flex Web Service token and a pre-configured Trade query in IBKR Account Management.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
# Recent trades (last ~7 days via API)
uv run python .claude/skills/ib-trades-history/scripts/trades.py --all-accounts

# Filter by symbol
uv run python .claude/skills/ib-trades-history/scripts/trades.py --all-accounts --symbol AAPL

# Full history via FlexReport
uv run python .claude/skills/ib-trades-history/scripts/trades.py --all-accounts --flex-token YOUR_TOKEN --flex-query-id YOUR_QUERY_ID

# Custom date range (FlexReport)
uv run python .claude/skills/ib-trades-history/scripts/trades.py --all-accounts --flex-token TOKEN --flex-query-id QID --start-date 2025-01-01 --end-date 2025-12-31

# Multiple queries (e.g., one per year to exceed 365-day limit)
uv run python .claude/skills/ib-trades-history/scripts/trades.py --all-accounts --flex-token TOKEN --flex-query-id QID_2025 --flex-query-id QID_2026 --start-date 2025-01-01 --end-date 2026-12-31

# From local FlexReport XML files (no TWS/Gateway needed)
uv run python .claude/skills/ib-trades-history/scripts/trades.py --file trades_2024.xml --file trades_2025.xml --symbol TSLA

# Mix files with date filtering
uv run python .claude/skills/ib-trades-history/scripts/trades.py --file exports/2025.xml --start-date 2025-06-01 --end-date 2025-12-31
```

## Arguments

- `--port` - IB port (default: 7496 for live trading)
- `--account` - Specific account ID to filter
- `--all-accounts` - Fetch trades for all managed accounts
- `--symbol` - Filter trades by symbol (e.g., AAPL)
- `--start-date` - Start date in YYYY-MM-DD format (default: Jan 1 of current year)
- `--end-date` - End date in YYYY-MM-DD format (default: today)
- `--flex-token` - FlexReport token (enables extended history)
- `--flex-query-id` - FlexReport query ID (repeatable — pass multiple to merge queries spanning different periods)
- `--file` - Local FlexReport XML file path (repeatable — pass multiple to merge files). No TWS/Gateway needed

**Default behavior** (no flags): fetches trades for the first managed account from the live API (~7 days).
**Always use `--all-accounts`** unless the user asks for a specific account.

## Data Sources

| Scenario | Source | Date Range |
|---|---|---|
| No flex args | `reqExecutionsAsync` | ~last 7 days |
| `--flex-token` + `--flex-query-id` | `FlexReport` (web) | As configured in query |
| `--file` | `file` (local XML) | Full file contents |

When using the live API, a `data_limitation` warning is included in the output.

## Output

Returns JSON with:
- `connected` - Whether connection succeeded
- `source` - Data source used (`reqExecutionsAsync` or `FlexReport`)
- `filters` - Applied filters (dates, symbol, account)
- `data_limitation` - Warning about API date limits (only when using live API)
- `execution_count` - Total number of executions returned
- `executions` - List of individual trade executions
- `summary` - Aggregated stats per symbol (bought, sold, commission, realized P&L)

If not connected, explain that TWS/Gateway needs to be running.

## Dependencies

- `ib-async`

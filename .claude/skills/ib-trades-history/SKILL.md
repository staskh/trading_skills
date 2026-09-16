---
name: ib-trades-history
description: Fetch trade executions from Interactive Brokers filtered by account, date range, or symbol. Supports live API (~7 days history) and FlexReport (full history). Use when user asks about their trades, executions, or transaction history. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Trades History

Fetch trade executions from Interactive Brokers.

## IB Connection

TWS or IB Gateway must be running locally with API enabled:
- **Paper trading** — port 7497
- **Live trading** — port 7496
- **`IB_PORT` env var** — default port when `--port` is omitted (e.g. `IB_PORT=4001` for a Gateway container). Precedence: `--port` flag > `IB_PORT` > built-in default. Set it in the shell or a `.env` file.

**Port fallback:** If the configured port fails, automatically retry on the other port.
If the retry succeeds, save to memory which account type worked (live/paper) and reuse it for all IB skill calls in this and future sessions — until the user explicitly asks for the other account.
If both ports fail, ask the user to verify that TWS or IB Gateway is running with API access enabled.

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

# Group option fills into vertical spreads (credit, width, max risk, capture %, RoR)
uv run python .claude/skills/ib-trades-history/scripts/trades.py --file exports/2026.xml --symbol NDX --group-spreads
```

## Arguments

- `--port` - IB port (default: 7497 for paper trading)
- `--account` - Specific account ID to filter
- `--all-accounts` - Fetch trades for all managed accounts
- `--symbol` - Filter trades by symbol (e.g., AAPL)
- `--start-date` - Start date in YYYY-MM-DD format (default: Jan 1 of current year)
- `--end-date` - End date in YYYY-MM-DD format (default: today)
- `--flex-token` - FlexReport token (enables extended history)
- `--flex-query-id` - FlexReport query ID (repeatable — pass multiple to merge queries spanning different periods)
- `--file` - Local FlexReport XML file path (repeatable — pass multiple to merge files). No TWS/Gateway needed
- `--group-spreads` - Consolidate fills into legs and pair them into vertical spreads. FlexReport sources only

**Default behavior** (no flags): fetches trades for the first managed account from the live API.
**Always use `--all-accounts`** unless the user asks for a specific account.

`--flex-token` / `--flex-query-id` may be omitted when `IB_FLEX_TOKEN` / `IB_FLEX_QUERY_ID`
are set in the environment or `.env` (see `env.template`). Flags win over env vars.

## Data Sources

| Scenario | Source | Date Range |
|---|---|---|
| No flex args | `reqExecutionsAsync` | **Current session only** |
| `--flex-token` + `--flex-query-id` | `FlexReport` (web) | As configured in query |
| `--file` | `file` (local XML) | Full file contents |

When using the live API, a `data_limitation` warning is included in the output.

**The live API returns only the current TWS session**, despite the "~7 days" the API
docs imply — it yields 0 executions on a weekend or for any prior-day lookback, which
looks identical to "no trades." Setting `ExecutionFilter.time` does not widen it. For
anything beyond today, use FlexReport. The web service is also aggressively
rate-limited ("Statement could not be generated at this time" = throttled, roughly one
generation per query per 10–15 min); for large lookbacks prefer a manual XML export
via `--file`.

## Spread Grouping (`--group-spreads`)

Turns raw fills into the trade-level view: a 10-lot order routed across five exchanges
is one leg, and its opening and closing legs are one spread.

Requires the `openCloseIndicator` field, which **only FlexReport sources provide**. On
the live API path the output carries `spread_grouping.supported = false` with a reason
rather than guessing which fills opened versus closed.

Legs are keyed on `(account, symbol, expiry, right)` — deliberately *not* trade date, so
a spread opened one session and settled the next keeps its closing legs.

Anything that is not an unambiguous two-strike vertical is left in `ungrouped_legs` with
a reason in `spread_grouping.warnings`, never force-fit into a bogus spread:
rolls, ratio spreads, multiple verticals on one expiry/right, single legs, positions
still open, and closes whose open predates the window.

`spread_grouping.reconciled` asserts that spread P&L plus ungrouped P&L equals the raw
execution P&L — check it before trusting a report.

## Output

Returns JSON with:
- `connected` - Whether connection succeeded
- `source` - Data source used (`reqExecutionsAsync` or `FlexReport`)
- `filters` - Applied filters (dates, symbol, account)
- `data_limitation` - Warning about API date limits (only when using live API)
- `execution_count` - Total number of executions returned
- `executions` - List of individual trade executions
- `summary` - Aggregated stats per symbol (bought, sold, commission, realized P&L)

With `--group-spreads`, also:
- `legs` / `leg_count` - Partial fills consolidated into orders
- `spreads` / `spread_count` - Paired verticals, each with `type` (Bear call / Bull put /
  Bull call / Bear put), `short_strike`, `long_strike`, `width`, `lots`, `credit`,
  `max_credit`, `max_risk`, `entry_date`/`entry_time`, `exit_date`/`exit_time`,
  `realizedPnL`, `commission`, `netPnL`, `capture_pct`, `return_on_risk_pct`,
  `settled_at_expiry`, `same_day`
- `ungrouped_legs` - Legs that are not a clean vertical (only when non-empty)
- `spread_grouping` - `supported`, `warnings`, `ungrouped_leg_count`, and the
  `reconciled` / `execution_pnl` / `spread_pnl` / `ungrouped_pnl` check

`max_risk` assumes a defined-risk vertical: `(width − credit) × lots × multiplier`.
`capture_pct` is realized P&L as a share of max credit; `return_on_risk_pct` is realized
P&L over max risk. On an iron condor the two wings are separate spreads — summing their
`max_risk` overstates true exposure, since only one side can lose at expiry.

If not connected, explain that TWS/Gateway needs to be running.

## Dependencies

- `ib-async`

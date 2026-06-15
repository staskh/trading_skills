---
name: ib-account
description: Get account summary from Interactive Brokers including cash balance, buying power, and account value. Use when user asks about their account, balance, buying power, or available cash. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Account

Fetch account summary from Interactive Brokers.

## IB Connection

TWS or IB Gateway must be running locally with API enabled:
- **Paper trading** — port 7497
- **Live trading** — port 7496

**Port fallback:** If the configured port fails, automatically retry on the other port.
If the retry succeeds, save to memory which account type worked (live/paper) and reuse it for all IB skill calls in this and future sessions — until the user explicitly asks for the other account.
If both ports fail, ask the user to verify that TWS or IB Gateway is running with API access enabled.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/account.py [--port PORT] [--account ACCOUNT_ID] [--all-accounts]
```

## Arguments

- `--port` - IB port (default: 7497 for paper trading)
- `--account` - Specific account ID to fetch
- `--all-accounts` - Fetch summaries for all managed accounts

**Default behavior** (no flags): fetches the first managed account only.
**Always use `--all-accounts`** unless the user asks for a specific account.

## Output

Returns JSON with:
- `connected` - Whether connection succeeded
- `accounts` - List of account summaries, each with account ID, net liquidation, cash, buying power, etc.

If not connected, explain that TWS/Gateway needs to be running.

## Dependencies

- `ib-async`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
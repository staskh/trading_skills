---
name: ib-account
description: Get account summary from Interactive Brokers including cash balance, buying power, and account value. Use when user asks about their account, balance, buying power, or available cash. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Account

Fetch account summary from Interactive Brokers.

## Prerequisites

User must have TWS or IB Gateway running locally with API enabled:
- Paper trading: port 7497
- Live trading: port 7496

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/account.py [--port PORT]
```

## Arguments

- `--port` - IB port (default: 7497 for paper trading)

## Output

Returns JSON with:
- `connected` - Whether connection succeeded
- `account` - Account ID
- `summary` - Net liquidation, cash, buying power, etc.

If not connected, explain that TWS/Gateway needs to be running.

## Dependencies

- `ib-async`

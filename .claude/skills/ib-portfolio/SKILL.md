---
name: ib-portfolio
description: Get portfolio positions from Interactive Brokers. Use when user asks about their portfolio, positions, holdings, or what stocks they own. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Portfolio

Fetch current portfolio positions from Interactive Brokers.

## Prerequisites

User must have TWS or IB Gateway running locally with API enabled:
- Paper trading: port 7497
- Live trading: port 7496

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/portfolio.py [--port PORT]
```

## Arguments

- `--port` - IB port (default: 7496 for live trading)
- `--account` - Specific IB account ID (optional, defaults to first account)

## Output

Returns JSON with:
- `connected` - Whether connection succeeded
- `positions` - Array of positions with symbol, quantity, avg_cost, market_value, unrealized_pnl

If not connected, explain that TWS/Gateway needs to be running.

## Dependencies

- `ib-async`

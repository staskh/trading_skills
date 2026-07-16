---
name: ib-portfolio
description: Get portfolio positions from Interactive Brokers. Use when user asks about their portfolio, positions, holdings, or what stocks they own. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Portfolio

Fetch current portfolio positions from Interactive Brokers.

## IB Connection

TWS or IB Gateway must be running locally with API enabled:
- **Paper trading** — port 7497
- **Live trading** — port 7496
- **`IB_PORT` env var** — default port when `--port` is omitted (e.g. `IB_PORT=4001` for a Gateway container). Precedence: `--port` flag > `IB_PORT` > built-in default. Set it in the shell or a `.env` file.

**Port fallback:** If the configured port fails, automatically retry on the other port.
If the retry succeeds, save to memory which account type worked (live/paper) and reuse it for all IB skill calls in this and future sessions — until the user explicitly asks for the other account.
If both ports fail, ask the user to verify that TWS or IB Gateway is running with API access enabled.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/portfolio.py [--port PORT]
```

## Arguments

- `--port` - IB port (default: 7497 for paper trading)
- `--account` - Specific IB account ID (optional, defaults to first account)

## Output

Returns JSON with:
- `connected` - Whether connection succeeded
- `positions` - Array of positions with symbol, quantity, avg_cost, market_value, unrealized_pnl

If not connected, explain that TWS/Gateway needs to be running.

## Dependencies

- `ib-async`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
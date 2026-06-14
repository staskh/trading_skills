---
name: qt-trades
description: Get order history and executions (fills) from Questrade. Use when the user asks about their Questrade orders, trade history, fills, or what they bought/sold over a period. Read-only — does not place orders. Requires a Questrade refresh token configured locally.
dependencies: ["questrade-skills"]
---

# Questrade Trades

Fetch orders and executions from Questrade. Read-only.

## Instructions

```bash
uv run python scripts/trades.py orders [--all-accounts] [--start ISO8601] [--end ISO8601] [--state All|Open|Closed]
uv run python scripts/trades.py executions [--all-accounts] [--start ISO8601] [--end ISO8601]
```

Questrade requires a time window for historical orders/executions; without
`--start`/`--end`, orders returns open orders only. Times are ISO 8601,
e.g. 2026-06-01T00:00:00-05:00.

## Output

JSON with `orders` (symbol, side, type, state, qty, prices, times) or
`executions` (symbol, side, qty, price, commission, time).

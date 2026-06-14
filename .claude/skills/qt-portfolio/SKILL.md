---
name: qt-portfolio
description: Get current portfolio positions from Questrade with quantity, average cost, market price, market value, and unrealized P&L. Use when the user asks about their Questrade holdings, positions, or portfolio. Requires a Questrade refresh token configured locally.
dependencies: ["questrade-skills"]
---

# Questrade Portfolio

Fetch portfolio positions from Questrade. Read-only.

## Prerequisites

Same QUESTRADE_REFRESH_TOKEN setup as qt-account.

## Instructions

```bash
uv run python scripts/portfolio.py [--account ACCOUNT_NUMBER] [--all-accounts]
```

## Output

JSON with `positions` (symbol, quantity, avg_cost, market_price,
market_value, unrealized_pnl). Note: Questrade returns options with the
option symbol in `symbol` and does not separate sec_type the way IB does.

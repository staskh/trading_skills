---
name: qt-account
description: Get account summary from Questrade including cash, total equity, buying power, and per-currency (CAD/USD) balances. Use when the user asks about their Questrade account, balance, buying power, or available cash. Requires a Questrade refresh token configured locally.
dependencies: ["questrade-skills"]
---

# Questrade Account

Fetch account summary (balances) from Questrade. Read-only.

## Prerequisites

A one-time refresh token from Questrade > API Centre > Personal applications,
exposed as the QUESTRADE_REFRESH_TOKEN environment variable on first run.
After that, tokens rotate and persist automatically under ~/.questrade-skills.

## Instructions

```bash
uv run python scripts/account.py [--account ACCOUNT_NUMBER] [--all-accounts]
```

## Arguments

- `--account` - specific account number to fetch
- `--all-accounts` - summarize every account on the login

Default (no flags): first account only.

## Output

JSON with `connected` and `accounts` (each with cash, total equity, buying
power, maintenance excess, and per-currency breakdown). If `connected` is
false, the refresh token likely expired (3-day limit) or was already used —
regenerate it in the API Centre.

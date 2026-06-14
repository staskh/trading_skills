---
name: qt-delta-exposure
description: Calculate delta-adjusted notional exposure for a Questrade portfolio, broken down by underlying and by account. Use when the user asks about their net market exposure, directional risk, delta, or how long/short their Questrade portfolio really is once options are accounted for. Requires a Questrade refresh token configured locally.
dependencies: ["questrade-skills", "trading-skills"]
---

# Questrade Delta Exposure

Computes delta-adjusted notional exposure across a Questrade portfolio,
treating stock delta as 1 and pricing option delta with Black-Scholes.

## Instructions

```bash
uv run python scripts/delta_exposure.py [--account ACCOUNT_NUMBER] [--single]
```

Default: all accounts. Use `--single` (with optional `--account`) for one.

## Method & caveats

- Stock positions: delta = 1, exposure = qty * spot.
- Option positions: exposure = delta * qty * 100 * spot, where delta is a
  Black-Scholes estimate using an IV approximation (no live IV feed). This
  mirrors the original IB module's approach and is fine for a risk read, not
  for precise hedging.
- Spot prices are delayed (yfinance). Canadian tickers may need an exchange
  suffix (e.g. .TO) to resolve; US underlyings resolve cleanly.

## Output

JSON with per-position rows plus `delta_notional_by_underlying`,
`delta_notional_by_account`, and `total_delta_notional`.

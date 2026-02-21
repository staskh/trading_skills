---
name: greeks
description: Calculate option Greeks (delta, gamma, theta, vega) and implied volatility for specific options. Use when user asks about Greeks, delta, gamma, theta, vega, IV, or option sensitivity analysis.
dependencies: ["trading-skills"]
---

# Option Greeks

Calculate Greeks for options using Black-Scholes model. Computes IV from market price via Newton-Raphson.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/greeks.py --spot SPOT --strike STRIKE --type call|put [--expiry YYYY-MM-DD | --dte DTE] [--price PRICE] [--date YYYY-MM-DD] [--vol VOL] [--rate RATE]
```

## Arguments

- `--spot` - Underlying spot price (required)
- `--strike` - Option strike price (required)
- `--type` - Option type: call or put (required)
- `--expiry` - Expiration date YYYY-MM-DD (use this OR --dte)
- `--dte` - Days to expiration (alternative to --expiry)
- `--date` - Calculate as of this date instead of today (YYYY-MM-DD)
- `--price` - Option market price (for IV calculation)
- `--vol` - Override volatility as decimal (e.g., 0.30 for 30%)
- `--rate` - Risk-free rate (default: 0.05)

## Output

Returns JSON with:
- `spot` - Underlying spot price
- `strike` - Strike price
- `days_to_expiry` - Days until expiration
- `iv` - Implied volatility (calculated from market price)
- `greeks` - delta, gamma, theta, vega, rho

## Examples

```bash
# With expiry date and market price (calculates IV)
uv run python scripts/greeks.py --spot 630 --strike 600 --expiry 2026-05-15 --type call --price 72.64

# With DTE directly
uv run python scripts/greeks.py --spot 630 --strike 600 --dte 30 --type call --price 40

# As of a future date
uv run python scripts/greeks.py --spot 630 --strike 600 --expiry 2026-05-15 --date 2026-03-01 --type call --price 50
```

Explain what each Greek means for the position.

## Dependencies

- `scipy`

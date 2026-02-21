---
name: scanner-pmcc
description: Scan stocks for Poor Man's Covered Call (PMCC) suitability. Analyzes LEAPS and short call options for delta, liquidity, spread, IV, and yield. Use when user asks about PMCC candidates, diagonal spreads, or LEAPS strategies.
dependencies: ["trading-skills"]
---

# PMCC Scanner

Finds optimal Poor Man's Covered Call setups by scoring symbols on option chain quality.

## What is PMCC?

Buy deep ITM LEAPS call (delta ~0.80) + Sell short-term OTM call (delta ~0.20) against it. Cheaper alternative to covered calls.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/scan.py SYMBOLS [options]
```

## Arguments

- `SYMBOLS` - Comma-separated tickers or path to JSON file from bullish scanner
- `--min-leaps-days` - Minimum LEAPS expiration in days (default: 270 = 9 months)
- `--leaps-delta` - Target LEAPS delta (default: 0.80)
- `--short-delta` - Target short call delta (default: 0.20)
- `--output` - Save results to JSON file

## Scoring System (max ~11 points)

| Category | Condition | Points |
|----------|-----------|--------|
| **Delta Accuracy** | LEAPS within ±0.05 | +2 |
| | LEAPS within ±0.10 | +1 |
| | Short within ±0.05 | +1 |
| | Short within ±0.10 | +0.5 |
| **Liquidity** | LEAPS vol+OI > 100 | +1 |
| | LEAPS vol+OI > 20 | +0.5 |
| | Short vol+OI > 500 | +1 |
| | Short vol+OI > 100 | +0.5 |
| **Spread** | LEAPS spread < 5% | +1 |
| | LEAPS spread < 10% | +0.5 |
| | Short spread < 10% | +1 |
| | Short spread < 20% | +0.5 |
| **IV Level** | 25-50% (ideal) | +2 |
| | 20-60% | +1 |
| **Yield** | Annual > 50% | +2 |
| | Annual > 30% | +1 |

## Output

Returns JSON with:
- `criteria` - Scan parameters used
- `results` - Array sorted by score:
  - `symbol`, `price`, `iv_pct`, `pmcc_score`
  - `leaps` - expiry, strike, delta, bid/ask, spread%, volume, OI
  - `short` - expiry, strike, delta, bid/ask, spread%, volume, OI
  - `metrics` - net_debit, short_yield%, annual_yield%, capital_required
- `errors` - Symbols that failed (no options, insufficient data)

## Examples

```bash
# Scan specific symbols
uv run python scripts/scan.py AAPL,MSFT,GOOGL,NVDA

# Use output from bullish scanner
uv run python scripts/scan.py bullish_results.json

# Custom delta targets
uv run python scripts/scan.py AAPL,MSFT --leaps-delta 0.70 --short-delta 0.15

# Longer LEAPS (1 year minimum)
uv run python scripts/scan.py AAPL,MSFT --min-leaps-days 365

# Save results
uv run python scripts/scan.py AAPL,MSFT,GOOGL --output pmcc_results.json
```

## Key Constraints

- Short strike **must be above** LEAPS strike
- Options with bid = 0 (illiquid) are skipped
- Moderate IV (25-50%) scores highest

## Interpretation

- Score > 9: Excellent candidate
- Score 7-9: Good candidate
- Score 5-7: Acceptable with caveats
- Score < 5: Poor liquidity or structure

## Dependencies

- `numpy`
- `pandas`
- `scipy`
- `yfinance`

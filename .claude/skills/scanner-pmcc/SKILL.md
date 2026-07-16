---
name: scanner-pmcc
description: Scan stocks for Poor Man's Covered Call (PMCC) suitability. Analyzes LEAPS and short call options for delta, liquidity, spread, IV, yield, trend direction, and earnings proximity. Use when user asks about PMCC candidates, diagonal spreads, or LEAPS strategies.
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
- `--output` - Save results to JSON file (use this; Claude generates the report from the JSON)
- `--report` - Save auto-generated markdown to file (programmatic fallback only — prefer Claude-generated reports)

## Scoring System (max possible: 14, range: -8 to 14)

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
| | Annual > 15% | +0.5 |
| **Trend** | Price > SMA50 | +1 / -1 |
| | RSI > 50 | +0.5 / -0.5 |
| | MACD > signal | +0.5 / -0.5 |
| **Earnings** | Next earnings > 45 days | +1.0 |
| | Earnings within 45 days | -1.0 |
| | Earnings within short expiry | -2.0 |
| **Weekly Options** | No weekly options listed | -1 |
| **Strike Density** | < 3 strikes spot→short | -2 |
| | < 5 strikes spot→short | -1 |
| **Short Premium** | Short mid < $0.10 | -1 |
| | Short mid < $0.50 | -0.5 |

Weekly-options, strike-density, and short-premium are penalty-only (0 at best), so
`max_possible_score` stays **14** while the theoretical minimum is **-8** (base 0,
trend -2, earnings -2, weekly -1, strike -2, short premium -1).

## Output

Returns JSON with:
- `criteria` - Scan parameters used
- `results` - Array sorted by score:
  - `symbol`, `price`, `iv_pct`, `pmcc_score`, `max_possible_score` (always 14)
  - `industry` - GICS industry (falls back to sector), or null
  - `description` - one-sentence company description, or null
  - `has_weeklies` - whether the symbol lists weekly options (bool)
  - `short_window` - short-expiry window actually used: `"7-21"` or `"5-30 (fallback)"`
  - `dividend_yield` - continuous dividend yield (fraction) used in the BS/IV math
  - `leaps` - expiry, strike, delta, **iv** (calculated from bid/ask), **last_price**, bid/ask, spread%, volume, OI
  - `short` - expiry, strike, delta, **iv** (calculated from bid/ask), **last_price**, bid/ask, spread%, volume, OI
  - `earnings_date` - next earnings date (YYYY-MM-DD) or null
  - `metrics` - net_debit, short_yield% (period yield over the short window), annual_yield%, capital_required
  - `score_breakdown` - every scoring component as a `<name>_delta` (float) + `<name>` (explanation string) pair:
    - Base: `leaps_delta`, `short_delta`, `leaps_liquidity`, `short_liquidity`, `leaps_spread`, `short_spread`, `iv`, `yield`
    - Trend: `trend_delta`, `trend` (per-indicator dict)
    - Earnings: `earnings_delta`, `earnings`
    - Weekly options: `weekly_options_delta`, `weekly_options`
    - Strike density: `strike_density_delta`, `strike_density`
    - Short premium: `short_premium_delta`, `short_premium`
    - All `_delta` values sum to `pmcc_score`
- `errors` - Symbols that failed (no options, insufficient data)

## Report Generation

When the user asks for a report, a written analysis, or a saved document:

1. Run the scanner with `--output` to capture JSON data:
   ```bash
   uv run python scripts/scan.py SYMBOLS --output sandbox/PMCC_Scan_YYYY-MM-DD_HHmm.json
   ```

2. Read the JSON output.

3. Generate the markdown report yourself using the template defined in `templates/markdown-template.md`. Do **not** use the `--report` flag — that produces mechanical string output. Claude-generated reports include real analysis, contextual warnings, and trader-relevant narrative.

4. Save the generated markdown to `sandbox/PMCC_Scan_YYYY-MM-DD_HHmm.md` (match the JSON timestamp).

5. Display the full report to the user.

## Examples

```bash
# Scan specific symbols
uv run python scripts/scan.py AAPL,MSFT,GOOGL,NVDA

# Scan and save JSON for report generation
uv run python scripts/scan.py AAPL,MSFT,GOOGL --output sandbox/PMCC_Scan_2026-01-15_1430.json

# Use output from bullish scanner
uv run python scripts/scan.py bullish_results.json

# Custom delta targets
uv run python scripts/scan.py AAPL,MSFT --leaps-delta 0.70 --short-delta 0.15

# Longer LEAPS (1 year minimum)
uv run python scripts/scan.py AAPL,MSFT --min-leaps-days 365
```

## IV Calculation

IV is always computed from market price data via Black-Scholes, never taken from Yahoo Finance's `impliedVolatility` column:

- **During trading hours**: IV derived from bid/ask mid price
- **Off-hours (bid=ask=0)**: IV derived from last price, using the option's last trade timestamp as the pricing moment (not current wall-clock time)

This applies to both `compute_atm_iv` (used for scanner baseline IV) and per-option delta calculations.

**Dividends**: the Black-Scholes inversion uses the underlying's continuous dividend
yield (Merton model). Ignoring it biases recovered IV downward for calls on dividend
payers — badly for high yielders (e.g. a 7%-yield name would read ~12% IV instead of
~24%). The yield is normalized from yfinance's inconsistent fields (`dividendRate/price`,
then `trailingAnnualDividendYield`, then `dividendYield`) and reported as `dividend_yield`
(a fraction) in each result. The same yield feeds the strike-selection deltas and the
max-profit repricing.

## Key Constraints

- Short strike **must be above** LEAPS strike
- Options with bid = 0 and no last price are skipped
- Moderate IV (25-50%) scores highest

## Interpretation

- Score > 12: Excellent candidate (strong structure + bullish trend + clear earnings runway)
- Score 10-12: Good candidate
- Score 6-10: Acceptable with caveats
- Score < 6: Poor structure, bearish trend, or earnings risk
- `max_possible_score` is always 14 — use `pmcc_score / max_possible_score` to gauge how close a candidate is to perfect
- **Off-hours scores are not comparable to market-hours scores.** When bid/ask aren't both > 0 (outside trading hours), `spread_pct` is forced to 100%, which zeroes out both spread scores (−2 vs a live scan). A candidate can look up to 2 points worse simply because it was scanned off-hours. Compare candidates only within the same scan.

## Dependencies

- `numpy`
- `pandas`
- `scipy`
- `yfinance`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
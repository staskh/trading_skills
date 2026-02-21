---
name: scanner-bullish
description: Scan stocks for bullish trends using technical indicators (SMA, RSI, MACD, ADX). Use when user asks to scan for bullish stocks, find trending stocks, or rank symbols by momentum.
---

# Bullish Scanner

Scans symbols for bullish trends and ranks them by composite score.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/scan.py SYMBOLS [--top N] [--period PERIOD]
```

## Arguments

- `SYMBOLS` - Comma-separated ticker symbols (e.g., `AAPL,MSFT,GOOGL,NVDA`)
- `--top` - Number of top results to return (default: 30)
- `--period` - Historical period for analysis: 1mo, 3mo, 6mo (default: 3mo)

## Scoring System (max ~8 points)

| Indicator | Condition | Points |
|-----------|-----------|--------|
| SMA20 | Price > SMA20 | +1.0 |
| SMA50 | Price > SMA50 | +1.0 |
| RSI | 50-70 (bullish) | +1.0 |
| | 30-50 (neutral) | +0.5 |
| | <30 (oversold) | +0.25 |
| MACD | MACD > Signal | +1.0 |
| | Histogram rising | +0.5 |
| ADX | >25 with +DI > -DI | +1.5 |
| | +DI > -DI only | +0.5 |
| Momentum | 3mo return / 20 | -1 to +2 |

## Output

Returns JSON with:
- `scan_date` - Timestamp of scan
- `symbols_scanned` - Total symbols analyzed
- `results` - Array sorted by score (highest first):
  - `symbol`, `score`, `price`
  - `next_earnings`, `earnings_timing` (BMO/AMC)
  - `period_return_pct`, `pct_from_sma20`, `pct_from_sma50`
  - `rsi`, `macd`, `adx`, `dmp`, `dmn`
  - `signals` - List of triggered conditions

## Examples

```bash
# Scan a few symbols
uv run python scripts/scan.py AAPL,MSFT,GOOGL,NVDA,TSLA

# Get top 10 from larger list
uv run python scripts/scan.py AAPL,MSFT,GOOGL,NVDA,TSLA,AMD,AMZN,META --top 10

# Use 6-month lookback
uv run python scripts/scan.py AAPL,MSFT,GOOGL --period 6mo
```

## Interpretation

- Score > 6: Strong bullish trend
- Score 4-6: Moderate bullish
- Score 2-4: Neutral/weak
- Score < 2: Bearish or no trend

## Dependencies

- `pandas`
- `pandas-ta`
- `yfinance`

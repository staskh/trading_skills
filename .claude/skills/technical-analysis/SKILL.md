---
name: technical-analysis
description: Compute technical indicators like RSI, MACD, Bollinger Bands, SMA, EMA for a stock. Use when user asks about technical analysis, indicators, RSI, MACD, moving averages, overbought/oversold, or chart analysis.
---

# Technical Analysis

Compute technical indicators using pandas-ta. Supports multi-symbol analysis and earnings data.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/technicals.py SYMBOL [--period PERIOD] [--indicators INDICATORS] [--earnings]
```

## Arguments

- `SYMBOL` - Ticker symbol or comma-separated list (e.g., `AAPL` or `AAPL,MSFT,GOOGL`)
- `--period` - Historical period: 1mo, 3mo, 6mo, 1y (default: 3mo)
- `--indicators` - Comma-separated list: rsi,macd,bb,sma,ema,atr,adx (default: all)
- `--earnings` - Include earnings data (upcoming date + history)

## Output

Single symbol returns:
- `price` - Current price and recent change
- `indicators` - Computed values for each indicator
- `risk_metrics` - Volatility (annualized %) and Sharpe ratio
- `signals` - Buy/sell signals based on indicator levels
- `earnings` - Upcoming date and EPS history (if `--earnings`)

Multiple symbols returns:
- `results` - Array of individual symbol results

## Interpretation

- RSI > 70 = overbought, RSI < 30 = oversold
- MACD crossover = momentum shift
- Price near Bollinger Band = potential reversal
- Golden cross (SMA20 > SMA50) = bullish
- ADX > 25 = strong trend
- Sharpe ratio > 1 = good risk-adjusted returns, > 2 = excellent
- Volatility (annualized) = standard deviation of returns scaled to annual basis

## Examples

```bash
# Single symbol with all indicators
uv run python scripts/technicals.py AAPL

# Multiple symbols
uv run python scripts/technicals.py AAPL,MSFT,GOOGL

# With earnings data
uv run python scripts/technicals.py NVDA --earnings

# Specific indicators only
uv run python scripts/technicals.py TSLA --indicators rsi,macd
```

---

# Correlation Analysis

Compute price correlation matrix between multiple symbols for diversification analysis.

## Instructions

```bash
uv run python scripts/correlation.py SYMBOLS [--period PERIOD]
```

## Arguments

- `SYMBOLS` - Comma-separated ticker symbols (minimum 2)
- `--period` - Historical period: 1mo, 3mo, 6mo, 1y (default: 3mo)

## Output

- `symbols` - List of symbols analyzed
- `period` - Time period used
- `correlation_matrix` - Nested dict with correlation values between all pairs

## Interpretation

- Correlation near 1.0 = highly correlated (move together)
- Correlation near -1.0 = negatively correlated (move opposite)
- Correlation near 0 = uncorrelated (independent movement)
- For diversification, prefer low/negative correlations

## Examples

```bash
# Portfolio correlation
uv run python scripts/correlation.py AAPL,MSFT,GOOGL,AMZN

# Sector comparison
uv run python scripts/correlation.py XLF,XLK,XLE,XLV --period 6mo

# Check hedge effectiveness
uv run python scripts/correlation.py SPY,GLD,TLT
```

## Dependencies

- `numpy`
- `pandas`
- `pandas-ta`
- `yfinance`

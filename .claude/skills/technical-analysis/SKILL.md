---
name: technical-analysis
description: Compute technical indicators like RSI, MACD, Bollinger Bands, SMA, EMA for a stock. Use when user asks about technical analysis, indicators, RSI, MACD, moving averages, overbought/oversold, or chart analysis.
dependencies: ["trading-skills"]
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

### Crossovers

- `indicators.macd.crossover` - Most recent MACD line/signal crossover, or `null`:
  - `direction` - `"up"` (MACD crossed above signal = bullish) or `"down"` (crossed below = bearish)
  - `days_ago` - Trading bars since the crossover (0 = happened on the most recent bar)
- `indicators.ema.crossover` - Most recent EMA9/EMA21 crossover (same shape; `null` if none).
  `indicators.ema` also reports `ema9` and `ema21` alongside `ema12`/`ema26`.

## Interpretation

- RSI > 70 = overbought, RSI < 30 = oversold
- MACD crossover = momentum shift; `crossover.days_ago` of 0-5 = fresh signal
- EMA9/21 crossover confirms short-term momentum; MACD typically leads, EMA confirms
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

# Intraday Technical Analysis

Same RSI/MACD/ADX-DMI math as above, computed on intraday (sub-daily) bars instead of daily closes. Daily-period indicators barely move within a single session — a whole trading day can pass with ADX unchanged to two decimal places — so they're the wrong tool for monitoring a position you plan to hold hours, not weeks. Use this for same-day/next-day position checks (day-trade or 1-3 day scalp monitoring); use the daily version above for swing/multi-week positions, or once at the start of a monitoring series as slower-moving regime context.

## Instructions

```bash
uv run python scripts/intraday_technicals.py SYMBOL [--interval INTERVAL] [--period PERIOD]
```

## Arguments

- `SYMBOL` - Ticker symbol
- `--interval` - Bar size: `1m`,`2m`,`5m`,`15m`,`30m`,`60m` (default: `5m`)
- `--period` - Lookback window: `1d`,`5d` (default: `1d` — today's session only)

## Output

- `bars` - Number of bars fetched. Early in the session this can be too few for stable indicators.
- `warnings` - Non-empty when `bars` is too low for RSI (~15+) or MACD's signal line (~35+) to be trustworthy — read this before trusting the numbers, don't just check for `null`.
- `price` - Current price, and change/change_pct measured from the first bar in the window (i.e. since session/period open, not vs. yesterday's close).
- `indicators.rsi`, `.macd` (`macd`/`signal`/`histogram`/`prev_histogram`), `.ema` (`ema9`/`ema21`/`crossover`), `.adx` (`adx`/`dmp`/`dmn`) - same fields and interpretation as the daily version, except `ema.crossover` reports age as `bars_ago` and `minutes_ago` (not `days_ago` — a crossover 4 bars back on 5m bars is 20 minutes old, not 4 days).

## Examples

```bash
# Default: 5-minute bars, today's session
uv run python scripts/intraday_technicals.py MU

# 15-minute bars for a slightly steadier read
uv run python scripts/intraday_technicals.py MU --interval 15m

# Include the prior session too (early in a new session, when today alone is too thin)
uv run python scripts/intraday_technicals.py MU --interval 5m --period 5d
```

## Gotcha

Right after the open there may be only a handful of bars — `compute_raw_indicators` still returns a number for RSI/ADX from whatever it has, it does not withhold output. Check `warnings` (or `bars`) rather than trusting a lone RSI value at 9:35 ET.

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


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
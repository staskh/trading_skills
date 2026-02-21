---
name: risk-assessment
description: Assess risk metrics for a stock or position including volatility, beta, VaR, and drawdown analysis. Use when user asks about risk, volatility, beta, VaR, value at risk, drawdown, or position sizing.
---

# Risk Assessment

Calculate risk metrics for stocks and positions.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/risk.py SYMBOL [--period PERIOD] [--position-size SIZE]
```

## Arguments

- `SYMBOL` - Ticker symbol
- `--period` - Analysis period: 1mo, 3mo, 6mo, 1y (default: 1y)
- `--position-size` - Dollar amount for position-specific metrics (optional)

## Output

Returns JSON with:
- `volatility` - Historical volatility (annualized)
- `beta` - Beta vs SPY
- `var_95` - 95% Value at Risk (daily)
- `var_99` - 99% Value at Risk (daily)
- `max_drawdown` - Maximum drawdown in period
- `sharpe_ratio` - Risk-adjusted return
- `position_risk` - If position-size provided, dollar VaR

Explain what the risk metrics mean and suggest position sizing if relevant.

## Dependencies

- `numpy`
- `yfinance`

# ABOUTME: Calculates risk metrics for stocks and positions.
# ABOUTME: Returns volatility, beta, VaR, drawdown, Sharpe ratio.

import numpy as np
import yfinance as yf

from trading_skills.utils import annualized_volatility


def calculate_risk_metrics(
    symbol: str, period: str = "1y", position_size: float | None = None
) -> dict:
    """Calculate risk metrics for a symbol."""
    ticker = yf.Ticker(symbol)

    # Get historical data
    hist = ticker.history(period=period)
    if hist.empty:
        return {"error": f"No data for {symbol}"}

    # Calculate daily returns and volatility
    returns, daily_vol, annual_vol = annualized_volatility(hist["Close"])

    if len(returns) < 20:
        return {"error": "Insufficient data for risk analysis"}

    # Current price
    current_price = hist["Close"].iloc[-1]

    # Beta calculation (vs SPY)
    spy = yf.Ticker("SPY")
    spy_hist = spy.history(period=period)
    spy_returns = spy_hist["Close"].pct_change().dropna()

    # Align dates
    common_idx = returns.index.intersection(spy_returns.index)
    if len(common_idx) > 20:
        stock_ret = returns.loc[common_idx]
        spy_ret = spy_returns.loc[common_idx]
        covariance = np.cov(stock_ret, spy_ret)[0, 1]
        spy_variance = np.var(spy_ret)
        beta = covariance / spy_variance if spy_variance > 0 else 1.0
    else:
        beta = None

    # Value at Risk (VaR) - parametric method
    mean_return = returns.mean()
    var_95 = mean_return - 1.645 * daily_vol  # 95% confidence
    var_99 = mean_return - 2.326 * daily_vol  # 99% confidence

    # Maximum drawdown
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min()

    # Sharpe ratio (assuming risk-free rate of 4%)
    risk_free_rate = 0.04
    excess_return = returns.mean() * 252 - risk_free_rate
    sharpe = excess_return / annual_vol if annual_vol > 0 else 0

    result = {
        "symbol": symbol.upper(),
        "period": period,
        "current_price": round(current_price, 2),
        "data_points": len(returns),
        "volatility": {
            "daily": round(daily_vol * 100, 2),
            "annual": round(annual_vol * 100, 2),
        },
        "beta": round(beta, 3) if beta else None,
        "var": {
            "var_95_daily": round(var_95 * 100, 2),
            "var_99_daily": round(var_99 * 100, 2),
        },
        "max_drawdown": round(max_drawdown * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "return": {
            "mean_daily": round(mean_return * 100, 4),
            "total_period": round((cumulative.iloc[-1] - 1) * 100, 2),
        },
    }

    # Position-specific metrics
    if position_size:
        result["position"] = {
            "size": position_size,
            "shares": int(position_size / current_price),
            "var_95_dollar": round(position_size * abs(var_95), 2),
            "var_99_dollar": round(position_size * abs(var_99), 2),
            "max_drawdown_dollar": round(position_size * abs(max_drawdown), 2),
        }

    return result

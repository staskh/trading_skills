# ABOUTME: Computes price correlation matrix between multiple symbols.
# ABOUTME: Use for portfolio diversification analysis and pair trading.

import pandas as pd
import yfinance as yf


def compute_correlation(symbols: list[str], period: str = "3mo") -> dict:
    """Compute correlation matrix between multiple symbols."""
    if len(symbols) < 2:
        return {"error": "Need at least 2 symbols for correlation"}

    prices = {}
    for symbol in symbols:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if not df.empty:
            prices[symbol.upper()] = df["Close"]

    if len(prices) < 2:
        return {"error": "Need at least 2 valid symbols with data for correlation"}

    # Create DataFrame and compute correlation
    price_df = pd.DataFrame(prices)
    corr_matrix = price_df.corr()

    # Convert to nested dict format
    result = {}
    for sym1 in corr_matrix.index:
        result[sym1] = {}
        for sym2 in corr_matrix.columns:
            result[sym1][sym2] = round(corr_matrix.loc[sym1, sym2], 4)

    return {
        "symbols": list(prices.keys()),
        "period": period,
        "correlation_matrix": result,
    }

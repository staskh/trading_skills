# ABOUTME: Fetches stock quote from Yahoo Finance.
# ABOUTME: Returns price, volume, market cap, and key metrics.

import yfinance as yf


def get_quote(symbol: str) -> dict:
    """Fetch current quote for a ticker symbol."""
    ticker = yf.Ticker(symbol)
    info = ticker.info

    # Handle case where ticker doesn't exist
    if not info or info.get("regularMarketPrice") is None:
        return {"error": f"No data found for symbol: {symbol}"}

    return {
        "symbol": symbol.upper(),
        "name": info.get("shortName", info.get("longName", "N/A")),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "change": info.get("regularMarketChange"),
        "change_percent": info.get("regularMarketChangePercent"),
        "volume": info.get("volume"),
        "avg_volume": info.get("averageVolume"),
        "market_cap": info.get("marketCap"),
        "high_52w": info.get("fiftyTwoWeekHigh"),
        "low_52w": info.get("fiftyTwoWeekLow"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
    }

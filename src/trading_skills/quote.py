# ABOUTME: Fetches stock quote from Yahoo Finance.
# ABOUTME: Returns price, volume, market cap, and key metrics.

import yfinance as yf

from .utils import is_trading_now, latest_trading_date


def get_quote(symbol: str) -> dict:
    """Fetch current quote for a ticker symbol."""
    ticker = yf.Ticker(symbol)
    info = ticker.info

    # Handle case where ticker doesn't exist
    if not info or info.get("regularMarketPrice") is None:
        return {"error": f"No data found for symbol: {symbol}"}

    # Before the regular session opens, Yahoo's regularMarket* fields still describe
    # the last COMPLETED session (yesterday's close vs the day before), not today —
    # so a pre-market call can return a "change" that is actually yesterday's already-
    # priced-in move. as_of_session pins down which session price/change belong to,
    # so callers don't relabel a stale move as "today's".
    return {
        "symbol": symbol.upper(),
        "name": info.get("shortName", info.get("longName", "N/A")),
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "change": info.get("regularMarketChange"),
        "change_percent": info.get("regularMarketChangePercent"),
        "as_of_session": str(latest_trading_date()),
        "market_open_now": is_trading_now(),
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

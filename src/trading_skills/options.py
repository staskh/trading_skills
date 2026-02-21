# ABOUTME: Fetches option chain data from Yahoo Finance.
# ABOUTME: Supports listing expiries and fetching chains by date.

import pandas as pd
import yfinance as yf

from trading_skills.utils import get_current_price


def get_expiries(symbol: str) -> list[str]:
    """Get available option expiration dates."""
    ticker = yf.Ticker(symbol)
    try:
        return list(ticker.options)
    except Exception:
        return []


def get_option_chain(symbol: str, expiry: str) -> dict:
    """Fetch option chain for a specific expiration date."""
    ticker = yf.Ticker(symbol)

    try:
        chain = ticker.option_chain(expiry)
    except Exception as e:
        return {"error": f"Failed to fetch option chain: {e}"}

    # Get underlying price
    info = ticker.info
    underlying_price = get_current_price(info)

    def safe_int(val):
        """Convert to int, handling NaN."""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return int(val)

    def safe_float(val, decimals=2):
        """Convert to float, handling NaN."""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return round(val, decimals)

    def process_options(df):
        """Convert options DataFrame to list of dicts."""
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "strike": row["strike"],
                    "bid": safe_float(row.get("bid")),
                    "ask": safe_float(row.get("ask")),
                    "lastPrice": safe_float(row.get("lastPrice")),
                    "volume": safe_int(row.get("volume")),
                    "openInterest": safe_int(row.get("openInterest")),
                    "impliedVolatility": safe_float(row.get("impliedVolatility", 0) * 100)
                    if row.get("impliedVolatility")
                    else None,
                    "inTheMoney": bool(row.get("inTheMoney", False)),
                }
            )
        return records

    return {
        "symbol": symbol.upper(),
        "source": "yfinance",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}/options?p={symbol}",
        "expiry": expiry,
        "underlying_price": underlying_price,
        "calls": process_options(chain.calls),
        "puts": process_options(chain.puts),
    }

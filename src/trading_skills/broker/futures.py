# ABOUTME: Centralized futures symbol registry shared across all broker modules.
# ABOUTME: Single source of truth for exchange mappings and Yahoo ticker conversions.

# Futures symbol -> IB exchange for ContFuture/FuturesOption qualification.
FUTURES_EXCHANGE = {
    "NQ": "CME",
    "ES": "CME",
    "RTY": "CME",
    "YM": "CBOT",
    "CL": "NYMEX",
    "GC": "COMEX",
    "SI": "COMEX",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
    "ZT": "CBOT",
    "6E": "CME",
    "6J": "CME",
    "6B": "CME",
}


def futures_yahoo_ticker(symbol: str) -> str:
    """Return the Yahoo Finance continuous-futures ticker for a symbol.

    Appends the '=F' suffix required by yfinance (e.g. NQ -> NQ=F).
    Safe to call repeatedly — already-suffixed symbols are returned unchanged.
    """
    if symbol.endswith("=F"):
        return symbol
    return f"{symbol}=F"

# ABOUTME: Fetches historical price data from Yahoo Finance.
# ABOUTME: Returns OHLCV data for specified period and interval.

import yfinance as yf


def get_history(symbol: str, period: str = "1mo", interval: str = "1d") -> dict:
    """Fetch historical price data."""
    ticker = yf.Ticker(symbol)

    try:
        df = ticker.history(period=period, interval=interval)
    except Exception as e:
        return {"error": f"Failed to fetch history: {e}"}

    if df.empty:
        return {"error": f"No history data for {symbol}"}

    data = []
    for date, row in df.iterrows():
        data.append(
            {
                "date": date.strftime("%Y-%m-%d %H:%M:%S")
                if interval in ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"]
                else date.strftime("%Y-%m-%d"),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            }
        )

    return {
        "symbol": symbol.upper(),
        "period": period,
        "interval": interval,
        "count": len(data),
        "data": data,
    }

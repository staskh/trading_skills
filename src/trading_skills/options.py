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

    def process_options(df):
        """Convert options DataFrame to list of dicts."""
        out = pd.DataFrame(index=df.index)

        out["contractSymbol"] = df["contractSymbol"]
        out["strike"] = df["strike"]

        # Vectorised rounding; NaN stays NaN (converted to None in final pass).
        for col in ("bid", "ask", "lastPrice"):
            out[col] = df[col].round(2)

        # tz_convert the whole datetime Series at once, then isoformat per element
        # (isoformat is not vectorisable, but the tz shift itself is).
        ltd = df["lastTradeDate"]
        if pd.api.types.is_datetime64_any_dtype(ltd):
            out["lastTradeDate"] = ltd.dt.tz_convert("America/New_York").apply(
                lambda x: x.isoformat() if pd.notna(x) else None
            )
        else:
            out["lastTradeDate"] = ltd

        for col in ("volume", "openInterest"):
            out[col] = df[col].apply(lambda x: int(x) if pd.notna(x) else None)

        # Multiply entire IV column at once; mask zeros/NaN in one step.
        iv = df["impliedVolatility"]
        out["impliedVolatility"] = (iv * 100).round(2).where(iv.notna() & (iv > 0))

        out["inTheMoney"] = df["inTheMoney"].fillna(False).astype(bool)

        # to_dict("records") is C-level fast; single pass to replace float NaN → None.
        return [
            {k: None if (isinstance(v, float) and pd.isna(v)) else v for k, v in row.items()}
            for row in out.to_dict("records")
        ]

    return {
        "symbol": symbol.upper(),
        "source": "yfinance",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}/options?p={symbol}",
        "expiry": expiry,
        "underlying_price": underlying_price,
        "calls": process_options(chain.calls),
        "puts": process_options(chain.puts),
    }

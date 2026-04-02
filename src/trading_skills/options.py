# ABOUTME: Fetches option chain data from Yahoo Finance.
# ABOUTME: Supports listing expiries and fetching chains by date.

from datetime import date, datetime

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


def parse_option_ticker(ticker: str) -> tuple[str, str, float, date]:
    """Parse an option ticker into its components.

    Accepts both plain OCC format (e.g. "NVDA260320P00170000") and
    Polygon format with "O:" prefix (e.g. "O:NVDA260320P00170000").

    OCC standard symbology — fixed-width 15-char suffix:
      <underlying> + YYMMDD(6) + C/P(1) + strike*1000 zero-padded to 8 digits

    OCC adjusted symbology for long underlyings — 16-char suffix:
      <underlying> + YYYMMDD(7) + C/P(1) + strike*1000 zero-padded to 8 digits
      where YYY = year - 1900  (e.g. 125 → 2025).
      Reference: OCC Symbology, https://www.theocc.com/clearing/clearing-services/symbology

    Disambiguation: try 6-digit date first; if the remaining underlying
    contains non-alpha chars (e.g. "BABA1"), the trailing digit belongs to
    the 7-digit date field instead.

    Returns:
        (underlying, type, strike, expiry) — type is "call" or "put".

    Raises:
        ValueError: if the ticker is too short to contain all fixed fields.
    """
    symbol = ticker.removeprefix("O:")

    if len(symbol) < 15:
        raise ValueError(f"Cannot parse option ticker: {ticker!r}")

    opt_type   = symbol[-9]       # C or P
    strike_str = symbol[-8:]      # strike * 1000, zero-padded

    underlying_6 = symbol[:-15]
    if underlying_6.isalpha():
        # Standard 6-digit date: YYMMDD
        underlying = underlying_6
        expiry = datetime.strptime(symbol[-15:-9], "%y%m%d").date()
    else:
        # Adjusted 7-digit date: YYYMMDD  (YYY = year - 1900)
        if len(symbol) < 16:
            raise ValueError(f"Cannot parse option ticker: {ticker!r}")
        underlying = symbol[:-16]
        date_str   = symbol[-16:-9]          # YYYMMDD
        year       = 1900 + int(date_str[:3])
        expiry     = datetime.strptime(f"{year}{date_str[3:]}", "%Y%m%d").date()

    return (
        underlying,
        "call" if opt_type.upper() == "C" else "put",
        int(strike_str) / 1000.0,
        expiry,
    )

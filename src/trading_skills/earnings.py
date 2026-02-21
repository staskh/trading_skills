# ABOUTME: Retrieves upcoming earnings dates for stock symbols.
# ABOUTME: Returns date, before/after market timing, and EPS estimate.

from datetime import datetime

import pandas as pd
import yfinance as yf


def get_next_earnings_date(symbol: str) -> str | None:
    """Get next earnings date string (YYYY-MM-DD) using 3-fallback chain."""
    try:
        ticker = yf.Ticker(symbol)

        # Method 1: calendar dict
        calendar = ticker.calendar
        if calendar and isinstance(calendar, dict):
            earnings_list = calendar.get("Earnings Date")
            if earnings_list and len(earnings_list) > 0:
                return str(earnings_list[0])[:10]

        # Method 2: earnings_dates DataFrame
        try:
            earnings_df = ticker.earnings_dates
            if earnings_df is not None and not earnings_df.empty:
                today = datetime.now().date()
                for idx in earnings_df.index:
                    earn_date = idx.date()
                    if earn_date >= today:
                        return str(earn_date)
        except Exception:
            pass

        # Method 3: info dict earningsTimestamp
        try:
            info = ticker.info
            earnings_ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
            if earnings_ts:
                earn_dt = datetime.fromtimestamp(earnings_ts)
                return earn_dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    except Exception:
        pass

    return None


def get_earnings_info(symbol: str) -> dict:
    """Get upcoming earnings info for a single symbol."""
    result = {"symbol": symbol.upper()}

    try:
        ticker = yf.Ticker(symbol)

        # Validate symbol exists by checking for basic info
        info = ticker.info
        if not info or info.get("regularMarketPrice") is None:
            result["error"] = f"Invalid symbol: {symbol}"
            result["earnings_date"] = None
            result["timing"] = None
            result["eps_estimate"] = None
            return result

        # Get earnings dates (includes future and past)
        earnings_dates = ticker.earnings_dates
        if earnings_dates is None or earnings_dates.empty:
            result["earnings_date"] = None
            result["timing"] = None
            result["eps_estimate"] = None
            return result

        # Find next upcoming earnings (first date in the future or most recent)
        now = pd.Timestamp.now(tz="America/New_York")

        # earnings_dates index is datetime, filter for future dates
        future_dates = earnings_dates[earnings_dates.index >= now]

        if future_dates.empty:
            # No future dates, use most recent
            next_earnings = earnings_dates.iloc[0]
            next_date = earnings_dates.index[0]
        else:
            # Use the soonest future date
            next_earnings = future_dates.iloc[-1]  # Last in future = soonest
            next_date = future_dates.index[-1]

        # Extract date
        if hasattr(next_date, "date"):
            result["earnings_date"] = str(next_date.date())
        else:
            result["earnings_date"] = str(next_date)[:10]

        # Determine timing (BMO = Before Market Open, AMC = After Market Close)
        if hasattr(next_date, "hour"):
            hour = next_date.hour
            if hour < 12:
                result["timing"] = "BMO"
            elif hour >= 16:
                result["timing"] = "AMC"
            else:
                result["timing"] = None
        else:
            result["timing"] = None

        # Get EPS estimate
        if "EPS Estimate" in next_earnings.index and pd.notna(next_earnings["EPS Estimate"]):
            result["eps_estimate"] = round(float(next_earnings["EPS Estimate"]), 3)
        else:
            result["eps_estimate"] = None

    except Exception as e:
        result["error"] = str(e)
        result["earnings_date"] = None
        result["timing"] = None
        result["eps_estimate"] = None

    return result


def get_multiple_earnings(symbols: list[str]) -> dict:
    """Get earnings info for multiple symbols, sorted by date."""
    results = []

    for symbol in symbols:
        info = get_earnings_info(symbol)
        results.append(info)

    # Sort by earnings_date (None values go to end)
    results.sort(key=lambda x: x.get("earnings_date") or "9999-99-99")

    return {"results": results}

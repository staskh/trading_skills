# ABOUTME: Retrieves upcoming earnings dates for stock symbols.
# ABOUTME: Returns date, before/after market timing, and EPS estimate.

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

_NY = ZoneInfo("America/New_York")


def get_next_earnings_date(symbol: str) -> str | None:
    """Get next earnings date string (YYYY-MM-DD) using 3-fallback chain.

    Dates before today (ET) are skipped in every source: Yahoo keeps a
    just-reported date in the calendar and info fields for days afterwards.
    """
    try:
        ticker = yf.Ticker(symbol)
        today = datetime.now(_NY).date()

        # Method 1: calendar dict
        calendar = ticker.calendar
        if calendar and isinstance(calendar, dict):
            listed = [date.fromisoformat(str(e)[:10]) for e in calendar.get("Earnings Date") or []]
            upcoming = [d for d in listed if d >= today]
            if upcoming:
                return str(min(upcoming))

        # Method 2: earnings_dates DataFrame (listed newest first)
        try:
            earnings_df = ticker.earnings_dates
            if earnings_df is not None and not earnings_df.empty:
                upcoming = [idx.date() for idx in earnings_df.index if idx.date() >= today]
                if upcoming:
                    return str(min(upcoming))
        except Exception:
            pass

        # Method 3: info dict earningsTimestamp
        try:
            info = ticker.info
            earnings_ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
            if earnings_ts:
                earn_date = datetime.fromtimestamp(earnings_ts, _NY).date()
                if earn_date >= today:
                    return str(earn_date)
        except Exception:
            pass

    except Exception:
        pass

    return None


def _last_reported(earnings_dates, now) -> dict:
    """Most recent past row with a reported EPS: date, actual, estimate, surprise %.

    When Yahoo lists the same timestamp more than once, the last of those rows
    in source order wins.
    """
    last = {
        "last_earnings_date": None,
        "last_eps_actual": None,
        "last_eps_estimate": None,
        "last_eps_surprise_pct": None,
    }
    if earnings_dates is None or earnings_dates.empty or "Reported EPS" not in earnings_dates:
        return last

    reported = earnings_dates[
        (earnings_dates.index <= now) & earnings_dates["Reported EPS"].notna()
    ]
    if reported.empty:
        return last

    reported = reported.sort_index(kind="stable")
    when = reported.index[-1]
    row = reported.iloc[-1]
    actual = float(row["Reported EPS"])
    estimate = row.get("EPS Estimate")
    estimate = float(estimate) if pd.notna(estimate) else None
    surprise = row.get("Surprise(%)")
    if pd.notna(surprise):
        surprise = float(surprise)
    elif estimate:
        surprise = (actual / estimate - 1) * 100
    else:
        surprise = None

    last["last_earnings_date"] = str(when.tz_convert("America/New_York").date())
    last["last_eps_actual"] = actual
    last["last_eps_estimate"] = estimate
    last["last_eps_surprise_pct"] = round(surprise, 2) if surprise is not None else None
    return last


def get_earnings_info(symbol: str) -> dict:
    """Get upcoming earnings info for a single symbol."""
    result = {"symbol": symbol.upper(), **_last_reported(None, None)}

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
        now = pd.Timestamp.now(tz="America/New_York")
        result.update(_last_reported(earnings_dates, now))
        if earnings_dates is None or earnings_dates.empty:
            result["earnings_date"] = None
            result["timing"] = None
            result["eps_estimate"] = None
            return result

        # Find next upcoming earnings (first date in the future or most recent)

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

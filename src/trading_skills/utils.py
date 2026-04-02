# ABOUTME: Shared utility functions used across trading analysis modules.
# ABOUTME: Type coercion, price extraction, date helpers, volatility, and NYSE calendar utilities.

import asyncio
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

_NYSE = mcal.get_calendar("NYSE")
_NY = ZoneInfo("America/New_York")


def is_trading_now() -> bool:
    """Return True if NYSE is currently open for regular trading."""
    now = datetime.now(_NY)
    schedule = _NYSE.schedule(start_date=str(now.date()), end_date=str(now.date()))
    if schedule.empty:
        return False
    open_t = schedule.iloc[0]["market_open"].to_pydatetime()
    close_t = schedule.iloc[0]["market_close"].to_pydatetime()
    return open_t <= now.astimezone(open_t.tzinfo) <= close_t


def latest_trading_date() -> date:
    """Return today if NYSE is open now, otherwise the most recent prior trading date."""
    today = datetime.now(_NY).date()
    schedule = _NYSE.schedule(
        start_date=str(today - pd.Timedelta(days=10)),
        end_date=str(today),
    )
    if schedule.empty:
        raise ValueError("No trading sessions found in the last 10 days")
    last_session = schedule.index[-1].date()
    # If today is a session day but market hasn't opened yet, use the previous session
    if last_session == today and not is_trading_now():
        now = datetime.now(_NY)
        open_t = schedule.iloc[-1]["market_open"].to_pydatetime().astimezone(_NY)
        if now < open_t:
            prev = schedule.iloc[:-1]
            return prev.index[-1].date() if not prev.empty else last_session
    return last_session


def _coerce_date(d) -> date:
    """Coerce datetime, date, or string to date."""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    # string: try ISO first, then YYYYMMDD
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(str(d), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {d!r}")


def previous_trading_date(d=None) -> date:
    """Return the NYSE trading date immediately preceding the given date."""
    ref = _coerce_date(d) if d is not None else datetime.now(_NY).date()
    schedule = _NYSE.schedule(
        start_date=str(ref - pd.Timedelta(days=10)),
        end_date=str(ref - pd.Timedelta(days=1)),
    )
    if schedule.empty:
        raise ValueError(f"No trading session found before {ref}")
    return schedule.index[-1].date()


def trading_sessions(from_date, to_date=None) -> list[date]:
    """Return sorted list of NYSE trading dates between from_date and to_date (inclusive).

    Args:
        from_date: start bound — datetime, date, or string (ISO or YYYYMMDD)
        to_date:   end bound — same types, or None to use today's date
    """
    start = _coerce_date(from_date)
    end = _coerce_date(to_date) if to_date is not None else datetime.now(_NY).date()
    schedule = _NYSE.schedule(start_date=str(start), end_date=str(end))
    return [idx.date() for idx in schedule.index]


def safe_value(val):
    """Convert pandas/numpy types to JSON-serializable types."""
    if pd.isna(val):
        return None
    if hasattr(val, "item"):
        return val.item()
    return val


async def fetch_with_timeout(coro, timeout: float, default=None):
    """Run coroutine with timeout, return default if timeout or error."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except (asyncio.TimeoutError, Exception):
        return default


def get_current_price(info: dict) -> float | None:
    """Extract current price from yfinance info dict."""
    return info.get("currentPrice") or info.get("regularMarketPrice")


def days_to_expiry(expiry_str: str) -> int:
    """Calculate days until expiration from YYYYMMDD string."""
    try:
        exp_date = datetime.strptime(expiry_str, "%Y%m%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return (exp_date - today).days
    except Exception:
        return 999


def annualized_volatility(close_series: pd.Series) -> tuple[pd.Series, float, float]:
    """Calculate annualized volatility from a price series.

    Returns (returns, daily_vol, annual_vol).
    """
    returns = close_series.pct_change().dropna()
    daily_vol = returns.std()
    annual_vol = daily_vol * math.sqrt(252)
    return returns, daily_vol, annual_vol


def format_expiry_iso(expiry_str: str) -> str:
    """Format YYYYMMDD to YYYY-MM-DD."""
    if len(expiry_str) == 8:
        return f"{expiry_str[:4]}-{expiry_str[4:6]}-{expiry_str[6:]}"
    return expiry_str


def format_expiry_long(expiry_str: str) -> str:
    """Format YYYYMMDD to 'Mon DD, YYYY'."""
    try:
        dt = datetime.strptime(expiry_str, "%Y%m%d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return expiry_str


def format_expiry_short(expiry_str: str) -> str:
    """Format YYYYMMDD to 'Mon DD'."""
    if not expiry_str:
        return "-"
    try:
        dt = datetime.strptime(expiry_str, "%Y%m%d")
        return dt.strftime("%b %d")
    except Exception:
        return expiry_str

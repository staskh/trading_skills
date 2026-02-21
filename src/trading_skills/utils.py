# ABOUTME: Shared utility functions used across trading analysis modules.
# ABOUTME: Includes type conversion, price extraction, date formatting, and volatility helpers.

import asyncio
import math
from datetime import datetime

import pandas as pd


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

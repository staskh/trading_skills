# ABOUTME: Detects option whale activity using Polygon.io second-level aggregation.
# ABOUTME: Identifies seconds with statistically anomalous dollar investment for a given option contract.

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from massive import RESTClient

from trading_skills.utils import _coerce_date, latest_trading_date

load_dotenv()

_NY = ZoneInfo("America/New_York")


def _make_client() -> RESTClient:
    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        raise EnvironmentError("MASSIVE_API_KEY not set")
    return RESTClient(api_key=api_key)


def option_whales(
    option_ticker: str,
    trading_date=None,
    sigma: float = 6,
) -> pd.DataFrame:
    """Find whale trades for an option contract — seconds with outlier dollar investment.

    Fetches all 1-second bars for the contract during market hours (9:30–16:00 NY)
    on the given date. investment = vwap × volume × 100 (contract size).
    Returns bars where investment > mean + sigma × std.

    Args:
        option_ticker: Option contract ticker (e.g. "O:NVDA260320P00170000").
        trading_date: Date to analyze (date, datetime, or "YYYY-MM-DD" string).
                      Defaults to latest trading day.
        sigma: Outlier threshold in standard deviations (default 6).

    Returns:
        DataFrame sorted by investment descending with columns:
        timestamp, open, high, low, close, volume, vwap, transactions, investment.
        timestamp is a timezone-aware datetime in America/New_York.
        Empty DataFrame if no whales found.
    """
    if trading_date is None:
        trading_date = latest_trading_date()
    else:
        trading_date = _coerce_date(trading_date)

    client = _make_client()

    bars = []
    for bar in client.list_aggs(
        option_ticker,
        1,
        "second",
        trading_date,
        trading_date,
        adjusted="true",
        sort="asc",
        limit=50000,
    ):
        bars.append(bar)

    if not bars:
        return pd.DataFrame()

    df = pd.DataFrame([b.__dict__ for b in bars])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(_NY)
    df["investment"] = (df["vwap"] * df["volume"] * 100).round(2)

    df = df[df["investment"] > 0]
    if df.empty:
        return pd.DataFrame()

    mean = df["investment"].mean()
    std = df["investment"].std()
    if std == 0:
        return pd.DataFrame()

    threshold = mean + sigma * std
    outliers = (
        df[df["investment"] > threshold]
        .sort_values("investment", ascending=False)
        .reset_index(drop=True)
    )

    return outliers[["timestamp", "open", "high", "low", "close", "volume", "vwap", "transactions", "investment"]]

# ABOUTME: Detects option whale activity using Polygon.io second-level aggregation.
# ABOUTME: Identifies seconds with statistically anomalous dollar invested for a given option contract.

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
    sigma_z: float = 3.5,
    sigma: float = 3.0,
    return_all: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """Find whale trades for an option contract — seconds with outlier dollar invested.

    Fetches all 1-second bars for the contract during market hours (9:30–16:00 NY)
    on the given date. invested = vwap × volume × 100 (contract size).

    Detection method depends on sample size (n = bars with invested > 0):
      n <  30: Modified Z-Score  — bar is whale when Mzi > sigma_z
      n >= 30: median + sigma * std — bar is whale when invested > median + sigma * std

    Args:
        option_ticker: Option contract ticker (e.g. "O:NVDA260320P00170000").
        trading_date: Date to analyze (date, datetime, or "YYYY-MM-DD" string).
                      Defaults to latest trading day.
        sigma_z: Modified Z-Score threshold used when n < 30 (default 3.5).
        sigma: Std-deviation multiplier used when n >= 30 (default 3.0).
        return_all: If True, return (outliers, all_bars) tuple instead of just outliers.

    Returns:
        DataFrame of outliers sorted by timestamp descending, or (outliers, all_bars)
        tuple when return_all=True. Columns: timestamp, open, high, low, close,
        volume, vwap, transactions, invested. timestamp is NY-timezone-aware.
        Empty DataFrame(s) if no data found.
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

    _cols = ["timestamp", "open", "high", "low", "close", "volume", "vwap", "transactions", "invested"]
    _empty = pd.DataFrame(columns=_cols)

    if not bars:
        return (_empty, _empty) if return_all else _empty

    df = pd.DataFrame([b.__dict__ for b in bars])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(_NY)
    df["invested"] = (df["vwap"] * df["volume"] * 100).round(2)

    all_bars = df[_cols].reset_index(drop=True)

    df = df[df["invested"] > 0]
    if df.empty:
        return (_empty, all_bars) if return_all else _empty

    median = df["invested"].median()
    n = len(df)

    if n < 30:
        # Small sample: Modified Z-Score (Iglewicz & Hoaglin, 1993).
        #
        # With few bars, std is unstable — a single large value inflates it,
        # raising the threshold and hiding the whale.  MAD (Median Absolute
        # Deviation) is resistant to that distortion.
        #
        #   MAD  = median( |xi − median(x)| )
        #   Mzi  = 0.6745 × (xi − median(x)) / MAD
        #
        # 0.6745 = Φ⁻¹(0.75): makes MAD a consistent estimator of σ for
        # normal data, so the threshold is on the same scale as sigma.

        mad = (df["invested"] - median).abs().median()

        if mad == 0:
            # >50% of bars are identical — no outliers can be identified.
            return (_empty, all_bars) if return_all else _empty

        mask = 0.6745 * (df["invested"] - median) / mad > sigma_z

    else:
        # Large sample: median + sigma * std.
        #
        # With enough bars the std estimate is stable.  Using the median
        # (instead of mean) as the centre keeps the threshold robust against
        # the skewed investment distribution while std captures its spread.

        std = df["invested"].std()

        if std == 0:
            return (_empty, all_bars) if return_all else _empty

        mask = df["invested"] > median + sigma * std

    outliers = (
        df[mask]
        .sort_values("timestamp", ascending=False)
        .reset_index(drop=True)
    )[_cols]

    return (outliers, all_bars) if return_all else outliers

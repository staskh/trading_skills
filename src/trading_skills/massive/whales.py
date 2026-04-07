# ABOUTME: Detects option whale activity using Polygon.io second-level aggregation.
# ABOUTME: Identifies seconds with anomalous dollar invested for a given option contract.

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from zoneinfo import ZoneInfo

import pandas as pd
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from massive import RESTClient

from trading_skills.options import get_expiries, get_option_chain, parse_option_ticker
from trading_skills.utils import _coerce_date, latest_trading_date, previous_trading_date

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

    _cols = [
        "timestamp",
        "ticker",
        "type",
        "strike",
        "expiry",
        "close",
        "volume",
        "transactions",
        "invested",
        "break_even",
    ]
    _empty = pd.DataFrame(columns=_cols)

    if not bars:
        return (_empty, _empty) if return_all else _empty

    # get the underlying, type, strike, expiry from the option ticker
    underlying, type, strike, expiry = parse_option_ticker(option_ticker)

    df = pd.DataFrame([b.__dict__ for b in bars])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(_NY)
    df["close"] = df["vwap"]
    df["invested"] = (df["close"] * df["volume"] * 100).round(2)
    if type == "call":
        df["break_even"] = strike + df["close"]
    else:
        df["break_even"] = strike - df["close"]
    df["ticker"] = option_ticker.removeprefix("O:")
    df["type"] = type
    df["strike"] = strike
    df["expiry"] = expiry

    all_bars = df[_cols].reset_index(drop=True)

    df = df[df["invested"] > 0]
    if df.empty:
        return (_empty, all_bars) if return_all else _empty

    median = df["invested"].median()
    n = len(df)

    # Per-transaction rule: any bar averaging >= $1M per trade is a whale
    # regardless of the statistical threshold — these are institutional block trades.
    tx_mask = (
        df["transactions"].notna()
        & (df["transactions"] > 0)
        & (df["invested"] / df["transactions"] >= 1_000_000)
    )

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
            # All bars have identical investment (typically a single bar).
            # Can't rank outliers statistically — include everything and let
            # the per-transaction filter below discard low-value bars.
            mask = pd.Series(True, index=df.index)
        else:
            mask = (0.6745 * (df["invested"] - median) / mad > sigma_z) | tx_mask

    else:
        # Large sample: median + sigma * std.
        #
        # With enough bars the std estimate is stable.  Using the median
        # (instead of mean) as the centre keeps the threshold robust against
        # the skewed investment distribution while std captures its spread.

        std = df["invested"].std()

        if std == 0:
            mask = tx_mask
        else:
            mask = (df["invested"] > median + sigma * std) | tx_mask

    # Drop outliers averaging <= $100k per transaction — statistical detection
    # may flag high-invested seconds driven by many small retail trades, not
    # institutional block activity.
    low_tx = (
        mask
        & df["transactions"].notna()
        & (df["transactions"] > 0)
        & (df["invested"] / df["transactions"] <= 100_000)
    )

    outliers = (df[mask & ~low_tx].sort_values("timestamp", ascending=True).reset_index(drop=True))[
        _cols
    ]

    return (outliers, all_bars) if return_all else outliers


def _fetch_chain(underlying: str, expiry: str) -> list[dict]:
    """Fetch one expiry's option chain; returns [] on error."""
    chain = get_option_chain(underlying, expiry)
    if "error" in chain:
        return []
    rows = []
    for opt_type, contracts in [("call", chain["calls"]), ("put", chain["puts"])]:
        for c in contracts:
            rows.append({**c, "expiry": expiry, "type": opt_type})
    return rows


def _fetch_whales_parallel(
    candidates: pd.DataFrame,
    sigma: float,
    sigma_z: float,
) -> list[pd.DataFrame]:
    """Fetch per-second whale data for each candidate concurrently.

    Returns a list of non-empty DataFrames, one per candidate that had whale activity.
    Exceptions from individual candidates are swallowed so others still complete.
    """

    def fetch_one(row):
        poly_ticker = "O:" + row["contractSymbol"]
        try:
            w = option_whales(
                poly_ticker, trading_date=row["tradeDate"], sigma=sigma, sigma_z=sigma_z
            )
            return w[_WHALE_COLS] if not w.empty else None
        except Exception:
            return None

    rows = [row for _, row in candidates.iterrows()]
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(fetch_one, row): row for row in rows}
        results = [f.result() for f in as_completed(futures)]

    return [r for r in results if r is not None]


def _crude_filter(invested: pd.Series, sigma_z: float) -> pd.Series:
    """Boolean mask identifying outliers via Modified Z-Score (MAD-based).

    Options dollar-invested is heavily right-skewed; a std-based threshold gets
    inflated by high-dollar contracts (e.g. NVDA/SPY), causing high-volume cheap
    options to fall below the threshold and go undetected.

    MAD (Median Absolute Deviation) is resistant to that inflation:
        MAD  = median( |xi − median(x)| )
        Mzi  = 0.6745 × (xi − median(x)) / MAD

    A bar is flagged when Mzi > sigma_z.
    """
    median = invested.median()
    mad = (invested - median).abs().median()
    if mad == 0:
        return invested > median
    z_scores = 0.6745 * (invested - median) / mad
    return z_scores > sigma_z


_WHALE_COLS = [
    "timestamp",
    "ticker",
    "type",
    "strike",
    "expiry",
    "close",
    "volume",
    "transactions",
    "invested",
    "break_even",
]


def whales_hunter(
    underlying: str,
    max_months: int = 2,
    precise: bool = True,
    sigma: float = 3.0,
    sigma_z: float = 3.5,
    trading_date=None,
) -> dict:
    """Scan an underlying for whale option activity in two steps.

    Step 1 (crude): uses Yahoo Finance option chain data to find contracts
    with anomalous daily investment (invested > median + sigma * std).

    Step 2 (precise): if precise=True, drills into each candidate with
    Polygon per-second data via option_whales. Falls back to crude results
    if the precise step yields nothing.

    Args:
        underlying: Underlying ticker (e.g. "AAPL").
        max_months: Maximum months until expiration (default 2).
        precise: If True, refine with Polygon per-second data (default True).
        sigma: Std-deviation multiplier for outlier detection (default 3.0).
        sigma_z: Modified Z-Score threshold for option_whales small samples (default 3.5).
        trading_date: Date to analyze. Defaults to latest trading day.

    Returns:
        dict with:
          "whales": list of dicts with keys timestamp, ticker, type, strike,
                    expiry, close, volume, transactions, invested, break_even.
          "source": "massive" if precise step succeeded, else "yahoo only".
    """
    if trading_date is None:
        trading_date = latest_trading_date()
    else:
        trading_date = _coerce_date(trading_date)

    expiry_max = trading_date + relativedelta(months=max_months)
    prev_trading_date = previous_trading_date(trading_date)
    _empty = {"whales": [], "source": "yahoo only", "trading_date": trading_date}

    # --- Step 1: crude Yahoo Finance scan ---
    all_expiries = get_expiries(underlying)
    expiries = [e for e in all_expiries if date.fromisoformat(e) <= expiry_max]

    with ThreadPoolExecutor() as executor:
        chain_results = list(executor.map(lambda e: _fetch_chain(underlying, e), expiries))
    rows = [row for chain_rows in chain_results for row in chain_rows]

    if not rows:
        return _empty

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["lastTradeDate"]).copy()
    df["tradeDate"] = (
        pd.to_datetime(df["lastTradeDate"], utc=True).dt.tz_convert("America/New_York").dt.date
    )
    df = df[df["tradeDate"].isin([trading_date, prev_trading_date])].copy()

    if df.empty:
        return _empty

    df["invested"] = (df["lastPrice"].fillna(0) * df["volume"].fillna(0) * 100).round(2)
    active = df[df["invested"] > 0].copy()

    if active.empty:
        return _empty

    candidates = active[_crude_filter(active["invested"], sigma_z)].copy()

    if candidates.empty:
        return _empty

    # Map candidate columns to the shared whale schema
    crude = candidates.copy()
    crude["timestamp"] = pd.to_datetime(crude["lastTradeDate"], utc=True).dt.tz_convert(
        "America/New_York"
    )
    crude["ticker"] = crude["contractSymbol"]
    crude["close"] = crude["lastPrice"].round(2)
    crude["volume"] = crude["volume"].apply(lambda x: int(x) if pd.notna(x) else None)
    crude["transactions"] = None
    crude["expiry"] = crude["expiry"].apply(date.fromisoformat)
    crude["break_even"] = crude.apply(
        lambda r: (
            round(r["strike"] + r["close"], 4)
            if r["type"] == "call"
            else round(r["strike"] - r["close"], 4)
        ),
        axis=1,
    )
    crude_records = crude[_WHALE_COLS].to_dict("records")

    # --- Step 2: precise Polygon drill-down ---
    if not precise:
        return {"whales": crude_records, "source": "yahoo only", "trading_date": trading_date}

    whale_dfs = _fetch_whales_parallel(candidates, sigma=sigma, sigma_z=sigma_z)

    if whale_dfs:
        precise_df = pd.concat(whale_dfs, ignore_index=True)
        return {
            "whales": precise_df.to_dict("records"),
            "source": "massive",
            "trading_date": trading_date,
        }

    return {"whales": crude_records, "source": "yahoo only", "trading_date": trading_date}

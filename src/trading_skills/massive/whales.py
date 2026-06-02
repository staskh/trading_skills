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
from massive.exceptions import AuthError, BadResponse

from trading_skills.options import get_expiries, get_option_chain, parse_option_ticker
from trading_skills.utils import _coerce_date, latest_trading_date, previous_trading_date

load_dotenv()

_NY = ZoneInfo("America/New_York")


class WhaleDataError(RuntimeError):
    """Raised when the Massive/Polygon API cannot serve whale data.

    Covers fatal, account-wide failures — a missing/invalid API key or a plan
    that lacks the 1-second aggregate entitlement the precise drill-down needs.
    These must surface to the caller rather than be swallowed into an empty
    result, which would masquerade as a genuine "no whale activity" signal.
    """


# Substrings that mark a BadResponse body as a fatal auth/entitlement failure
# (as opposed to a recoverable per-contract error like a 404 for one ticker).
_FATAL_RESPONSE_MARKERS = (
    "NOT_AUTHORIZED",
    "not entitled",
    "Unknown API Key",
    "UNAUTHORIZED",
)


def _is_fatal_api_error(exc: Exception) -> bool:
    """True if exc is an account-wide auth/entitlement failure, not per-contract.

    Fatal: missing key (EnvironmentError), AuthError (empty/invalid key), or a
    BadResponse whose body names an authorization/entitlement problem. A bare
    BadResponse (e.g. a 404 for a single illiquid contract) is NOT fatal — those
    stay swallowed so the rest of the scan completes.
    """
    if isinstance(exc, (EnvironmentError, AuthError)):
        return True
    if isinstance(exc, BadResponse):
        return any(marker in str(exc) for marker in _FATAL_RESPONSE_MARKERS)
    return False


def _make_client() -> RESTClient:
    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        raise EnvironmentError("MASSIVE_API_KEY not set")
    return RESTClient(api_key=api_key)


def _modified_z_score(invested: pd.Series, sigma_z: float) -> pd.Series:
    """Boolean mask identifying outliers via Modified Z-Score (MAD-based).

    Robust to the right-skewed distribution of options dollar-invested.
    A std-based threshold gets inflated by high-dollar contracts (e.g. NVDA/SPY),
    causing high-volume cheap options to fall below the threshold undetected.

    MAD (Median Absolute Deviation) is resistant to that inflation:
        MAD  = median( |xi − median(x)| )
        Mzi  = 0.6745 × (xi − median(x)) / MAD

    0.6745 = Φ⁻¹(0.75): makes MAD a consistent estimator of σ for normal data,
    keeping the threshold on the same scale as sigma_z.

    A value is flagged when Mzi > sigma_z. When MAD = 0 (majority of values
    share the median, leaving deviation undefined), any value strictly above
    the median is flagged.
    """
    median = invested.median()
    mad = (invested - median).abs().median()
    if mad == 0:
        # Majority of values are at the median; flag anything strictly above it.
        return invested > median
    z_scores = 0.6745 * (invested - median) / mad
    return z_scores > sigma_z


def option_whales(
    option_ticker: str,
    trading_date=None,
    sigma_z: float = 3.5,
    return_all: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """Find whale trades for an option contract — seconds with outlier dollar invested.

    Fetches all 1-second bars for the contract during market hours (9:30–16:00 NY)
    on the given date. invested = vwap × volume × 100 (contract size).

    Detection uses Modified Z-Score (MAD-based) for all sample sizes:
        Mzi = 0.6745 × (xi − median) / MAD
    A bar is a whale when Mzi > sigma_z OR it averages >= $1M per transaction.

    Args:
        option_ticker: Option contract ticker (e.g. "O:NVDA260320P00170000").
        trading_date: Date to analyze (date, datetime, or "YYYY-MM-DD" string).
                      Defaults to latest trading day.
        sigma_z: Modified Z-Score threshold (default 3.5).
        return_all: If True, return (outliers, all_bars) tuple instead of just outliers.

    Returns:
        DataFrame of outliers sorted by timestamp ascending, or (outliers, all_bars)
        tuple when return_all=True. Columns: timestamp, ticker, type, strike, expiry,
        close, volume, transactions, invested, break_even. timestamp is NY-timezone-aware.
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
    _, opt_type, strike, expiry = parse_option_ticker(option_ticker)

    df = pd.DataFrame([b.__dict__ for b in bars])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert(_NY)
    df["close"] = df["vwap"]
    df["invested"] = (df["close"] * df["volume"] * 100).round(2)
    if opt_type == "call":
        df["break_even"] = strike + df["close"]
    else:
        df["break_even"] = strike - df["close"]
    df["ticker"] = option_ticker.removeprefix("O:")
    df["type"] = opt_type
    df["strike"] = strike
    df["expiry"] = expiry

    all_bars = df[_cols].reset_index(drop=True)

    df = df[df["invested"] > 0]
    if df.empty:
        return (_empty, all_bars) if return_all else _empty

    # Per-transaction rule: any bar averaging >= $1M per trade is a whale
    # regardless of the statistical threshold — these are institutional block trades.
    tx_mask = (
        df["transactions"].notna()
        & (df["transactions"] > 0)
        & (df["invested"] / df["transactions"] >= 1_000_000)
    )

    mask = _modified_z_score(df["invested"], sigma_z) | tx_mask

    # Drop outliers averaging <= $50k per transaction — statistical detection
    # may flag high-invested seconds driven by many small retail trades, not
    # institutional block activity.
    low_tx = (
        mask
        & df["transactions"].notna()
        & (df["transactions"] > 0)
        & (df["invested"] / df["transactions"] <= 50_000)
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
    sigma_z: float,
) -> list[pd.DataFrame]:
    """Fetch per-second whale data for each candidate concurrently.

    Returns a list of non-empty DataFrames, one per candidate that had whale activity.
    Recoverable per-candidate errors are swallowed so others still complete, but a
    fatal auth/entitlement failure (see _is_fatal_api_error) is re-raised as a
    WhaleDataError so it cannot be silently turned into an empty result.
    """

    def fetch_one(row):
        poly_ticker = "O:" + row["contractSymbol"]
        try:
            w = option_whales(poly_ticker, trading_date=row["tradeDate"], sigma_z=sigma_z)
            if w.empty:
                return None
            w["open_interest"] = row.get("open_interest")
            w["reason"] = row.get("reason")
            return w[_WHALE_COLS]
        except Exception as exc:
            if _is_fatal_api_error(exc):
                raise WhaleDataError(
                    "Massive API request failed — the key is missing/invalid or the "
                    "plan lacks the 1-second aggregate entitlement required for whale "
                    f"detection. Upgrade the plan or fix MASSIVE_API_KEY. Detail: {exc}"
                ) from exc
            return None

    rows = [row for _, row in candidates.iterrows()]
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(fetch_one, row): row for row in rows}
        results = []
        for f in as_completed(futures):
            results.append(f.result())  # re-raises WhaleDataError from fetch_one

    return [r for r in results if r is not None]


_WHALE_COLS = [
    "timestamp",
    "ticker",
    "type",
    "strike",
    "expiry",
    "close",
    "volume",
    "open_interest",
    "transactions",
    "invested",
    "break_even",
    "reason",
]


def _apply_crude_selection(active: pd.DataFrame, sigma_z: float) -> pd.DataFrame:
    """Select whale candidates and tag each with the selection reason.

    Two independent criteria (either suffices):
      - z_score : invested is a Modified Z-Score outlier across all active contracts
      - volume>oi: today's volume exceeds open interest (fresh positioning signal)

    The returned DataFrame has two extra columns:
      - open_interest : int or None (from openInterest in Yahoo chain data)
      - reason        : 'z_score' | 'volume>oi' | 'both'
    """
    zscore_mask = _modified_z_score(active["invested"], sigma_z)

    oi = (
        active["openInterest"]
        if "openInterest" in active.columns
        else pd.Series(float("nan"), index=active.index)
    )
    vol_oi_mask = active["volume"] > oi  # NaN OI → False (safe)

    candidates = active[zscore_mask | vol_oi_mask].copy()
    if candidates.empty:
        candidates["open_interest"] = pd.Series(dtype=object)
        candidates["reason"] = pd.Series(dtype=str)
        return candidates

    oi_sub = oi.loc[candidates.index]
    vol_sub = candidates["volume"]
    zs_sub = zscore_mask.loc[candidates.index]
    vo_sub = vol_sub > oi_sub

    candidates["open_interest"] = oi_sub.apply(lambda x: int(x) if pd.notna(x) else None)
    candidates["reason"] = "z_score"
    candidates.loc[vo_sub & ~zs_sub, "reason"] = "volume>oi"
    candidates.loc[vo_sub & zs_sub, "reason"] = "both"

    return candidates


def whales_hunter(
    underlying: str,
    max_months: int = 2,
    precise: bool = True,
    sigma_z: float = 3.5,
    trading_date=None,
) -> dict:
    """Scan an underlying for whale option activity in two steps.

    Step 1 (crude): uses Yahoo Finance option chain data to find contracts
    with anomalous daily investment, detected via Modified Z-Score (MAD-based).

    Step 2 (precise): if precise=True, drills into each candidate with
    Polygon per-second data via option_whales. Falls back to crude results
    if the precise step yields nothing.

    Args:
        underlying: Underlying ticker (e.g. "AAPL").
        max_months: Maximum months until expiration (default 2).
        precise: If True, refine with Polygon per-second data (default True).
        sigma_z: Modified Z-Score threshold for outlier detection (default 3.5).
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
    _empty = {"whales": [], "source": "yahoo", "trading_date": trading_date}

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

    candidates = _apply_crude_selection(active, sigma_z)

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
        return {"whales": crude_records, "source": "yahoo", "trading_date": trading_date}

    whale_dfs = _fetch_whales_parallel(candidates, sigma_z=sigma_z)

    if whale_dfs:
        precise_df = pd.concat(whale_dfs, ignore_index=True)
        return {
            "whales": precise_df.to_dict("records"),
            "source": "massive",
            "trading_date": trading_date,
        }

    return {"whales": [], "source": "massive", "trading_date": trading_date}

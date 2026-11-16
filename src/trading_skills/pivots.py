# ABOUTME: Daily floor-trader pivot levels (P, R1/R2, S1/S2) over recent sessions.
# ABOUTME: Classifies each symbol as near support, chasing a breakout, or neutral.

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from trading_skills.utils import generated_at_str, is_trading_now

NY = ZoneInfo("America/New_York")
SUPPORT_LEVELS = ("S2", "S1", "P")
RESISTANCE_LEVELS = ("R1", "R2")


def classic_pivots(high: float, low: float, close: float) -> dict:
    """Floor-trader pivots computed from one session's high, low and close."""
    p = (high + low + close) / 3
    rng = high - low
    return {
        "P": round(p, 4),
        "R1": round(2 * p - low, 4),
        "R2": round(p + rng, 4),
        "S1": round(2 * p - high, 4),
        "S2": round(p - rng, 4),
    }


def session_pivots(bars: pd.DataFrame, sessions: int = 5) -> list[dict]:
    """Pivot levels in force for each of the last `sessions` bars, with that bar's prices.

    The levels for a session come from the previous session's high, low and close.
    """
    rows = []
    for i in range(max(1, len(bars) - sessions), len(bars)):
        prior, bar = bars.iloc[i - 1], bars.iloc[i]
        rows.append(
            {
                "date": bars.index[i].strftime("%Y-%m-%d"),
                "levels": classic_pivots(prior["High"], prior["Low"], prior["Close"]),
                "high": round(float(bar["High"]), 4),
                "low": round(float(bar["Low"]), 4),
                "close": round(float(bar["Close"]), 4),
            }
        )
    return rows


def _find_breakout(history: list[dict]) -> dict | None:
    """Latest session that closed above its R1, and whether a later low came back to it."""
    for i in range(len(history) - 1, -1, -1):
        session = history[i]
        level = session["levels"]["R1"]
        if session["close"] > level:
            retested = any(later["low"] <= level for later in history[i + 1 :])
            return {"date": session["date"], "level": level, "retested": retested}
    return None


def classify_entry(
    price: float, current: dict, history: list[dict], tolerance_pct: float = 1.5
) -> dict:
    """Place `price` against the current pivot levels.

    Status is one of:
    - chase_risk: above the latest breakout level (a session close above that session's
      R1, or the current R1) and no later low came back to it
    - breakout_retested: above the latest breakout level after a pullback to it
    - near_support: within `tolerance_pct` above the nearest support (S2, S1 or P)
    - below_supports: under S2
    - neutral: anything else
    """
    supports = sorted(
        ((name, current[name]) for name in SUPPORT_LEVELS if current[name] <= price),
        key=lambda item: item[1],
        reverse=True,
    )
    resistances = sorted(
        ((name, current[name]) for name in RESISTANCE_LEVELS if current[name] > price),
        key=lambda item: item[1],
    )
    nearest = {"level": supports[0][0], "price": supports[0][1]} if supports else None
    following = {"level": supports[1][0], "price": supports[1][1]} if len(supports) > 1 else None
    pct_above = round((price - nearest["price"]) / nearest["price"] * 100, 2) if nearest else None

    result = {
        "nearest_support": nearest,
        "next_support": following,
        "pct_above_support": pct_above,
        "nearest_resistance": (
            {"level": resistances[0][0], "price": resistances[0][1]} if resistances else None
        ),
        "breakout": None,
    }

    breakout = _find_breakout(history)
    if breakout is None or price <= breakout["level"]:
        breakout = None
        if price > current["R1"]:
            breakout = {"date": "current", "level": current["R1"], "retested": False}

    if breakout:
        result["breakout"] = breakout
        result["status"] = "breakout_retested" if breakout["retested"] else "chase_risk"
    elif nearest is None:
        result["status"] = "below_supports"
    elif pct_above <= tolerance_pct:
        result["status"] = "near_support"
    else:
        result["status"] = "neutral"
    return result


def _symbol_bars(data: pd.DataFrame, symbol: str) -> pd.DataFrame:
    bars = data[symbol] if isinstance(data.columns, pd.MultiIndex) else data
    return bars[["Open", "High", "Low", "Close"]].dropna()


def pivot_status(
    bars: pd.DataFrame,
    sessions: int = 5,
    tolerance_pct: float = 1.5,
    drop_today_partial: bool = False,
) -> dict:
    """Price, current pivot levels, recent session pivots and entry status for one symbol.

    With `drop_today_partial` the last bar supplies the price only; the levels in force and
    the session history come from the bars before it.
    """
    price = round(float(bars["Close"].iloc[-1]), 4)
    completed = bars.iloc[:-1] if drop_today_partial else bars
    last = completed.iloc[-1]
    current = classic_pivots(last["High"], last["Low"], last["Close"])
    history = session_pivots(completed, sessions)
    return {
        "price": price,
        "current_levels": current,
        "sessions": history,
        **classify_entry(price, current, history, tolerance_pct),
    }


def is_partial_session(
    bars: pd.DataFrame, trading_now: bool | None = None, today: date | None = None
) -> bool:
    """True when the last bar is today's session still in progress."""
    if trading_now is None:
        trading_now = is_trading_now()
    if today is None:
        today = datetime.now(NY).date()
    return trading_now and bars.index[-1].date() == today


def get_pivot_levels(symbols: list[str], sessions: int = 5, tolerance_pct: float = 1.5) -> dict:
    """Pivot levels for the last `sessions` completed sessions and an entry status per symbol.

    During regular hours today's partial bar supplies the price only; the levels in force
    today come from the last completed session.
    """
    symbols = [s.upper() for s in symbols]
    data = yf.download(symbols, period="3mo", group_by="ticker", auto_adjust=False, progress=False)
    results = []
    for symbol in symbols:
        try:
            bars = _symbol_bars(data, symbol)
        except KeyError:
            bars = pd.DataFrame()
        if len(bars) < 2:
            results.append({"symbol": symbol, "error": "No price history"})
            continue

        status = pivot_status(
            bars,
            sessions,
            tolerance_pct,
            drop_today_partial=is_partial_session(bars),
        )
        results.append({"symbol": symbol, **status})

    return {
        "results": results,
        "tolerance_pct": tolerance_pct,
        "generated_at": generated_at_str(),
        "data_delay": "15min",
    }

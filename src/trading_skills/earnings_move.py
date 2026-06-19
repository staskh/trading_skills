# ABOUTME: Computes historical post-earnings price-reaction statistics for a symbol.
# ABOUTME: Powers an adaptive earnings gate whose severity scales with realized gap risk.

import math
import statistics
from bisect import bisect_left
from datetime import date, datetime
from zoneinfo import ZoneInfo

import yfinance as yf

_NY = ZoneInfo("America/New_York")

# Magnitude thresholds (fraction, not percent) for classifying a name's typical
# single-session earnings reaction.
LOW_MOVE_THRESHOLD = 0.03  # median |move| below this => low-volatility name
HIGH_MOVE_THRESHOLD = 0.07  # median |move| above this => high-gap name
TAIL_MOVE_THRESHOLD = 0.15  # any single |move| above this => treat as high-gap tail risk
MIN_EVENTS = 2  # need at least this many past earnings to trust the distribution

# Only earnings within this many calendar days can trigger the gate.
GATE_WINDOW_DAYS = 21


def _to_date(value) -> date | None:
    """Coerce a datetime, date, or ISO-ish string to a plain date (or None)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            continue
    return None


def reaction_moves(earnings_dates, closes) -> list[float]:
    """Measure the single-session price reaction around each past earnings date.

    For every earnings date we look at the trading session on/after the
    announcement (``d0``), its prior session (``d_prev``) and its next session
    (``d_next``), then take whichever 1-day return has the larger magnitude:
    ``close[d0]/close[d_prev]-1`` (captures a before-open report) vs
    ``close[d_next]/close[d0]-1`` (captures an after-close report). This is
    robust to BMO/AMC timing, which Yahoo frequently reports as None.

    Because timing is usually unknown, the larger-magnitude session is an UPPER
    BOUND on the true reaction: an unrelated large adjacent move (a macro day, a
    run-up into the print) can be mis-attributed, biasing the distribution high.
    The gate that consumes this only ever lowers a rating, so the bias is
    conservative. An event whose announcement maps to the final available
    session is skipped, since an after-close gap would land on a session not yet
    in the history.

    Args:
        earnings_dates: iterable of datetime/date/str earnings dates (any order).
        closes: a pandas Series of adjusted closes indexed by a DatetimeIndex.

    Returns:
        Signed reactions, one per resolvable earnings date, in the input order.
    """
    if closes is None or len(closes) < 3:
        return []

    # bisect_left requires an ascending index; guarantee it regardless of caller.
    closes = closes.sort_index()
    session_dates = [ts.date() if hasattr(ts, "date") else ts for ts in closes.index]
    values = [float(v) for v in closes.values]
    n = len(values)

    moves: list[float] = []
    for raw in earnings_dates:
        e_date = _to_date(raw)
        if e_date is None:
            continue
        # First session on/after the announcement date. Require both a prior
        # session (to measure against) and a following session (to confirm an
        # after-close reaction); otherwise the event is not yet measurable.
        i = bisect_left(session_dates, e_date)
        if i < 1 or i + 1 >= n:
            continue
        prev_close, d0_close, next_close = values[i - 1], values[i], values[i + 1]
        if not (
            math.isfinite(prev_close)
            and prev_close > 0
            and math.isfinite(d0_close)
            and d0_close > 0
            and math.isfinite(next_close)
            and next_close > 0
        ):
            continue  # corporate-action / NaN rows would poison the distribution
        r1 = d0_close / prev_close - 1.0  # before-open (BMO) reaction
        r2 = next_close / d0_close - 1.0  # after-close (AMC) reaction
        reaction = r1 if abs(r1) >= abs(r2) else r2
        moves.append(reaction)
    return moves


def _classify(median_abs: float, max_abs: float) -> str:
    """Bucket a move distribution into low / moderate / high gap risk."""
    if median_abs > HIGH_MOVE_THRESHOLD or max_abs > TAIL_MOVE_THRESHOLD:
        return "high"
    if median_abs < LOW_MOVE_THRESHOLD and max_abs < 0.10:
        return "low"
    return "moderate"


def summarize_moves(moves: list[float]) -> dict:
    """Summarize signed earnings reactions into a stats dict.

    ``moves`` is expected most-recent-first so ``last_move`` is the latest event.
    """
    moves = [m for m in moves if math.isfinite(m)]
    n = len(moves)
    if n < MIN_EVENTS:
        return {"data_available": False, "n_events": n}

    abs_moves = [abs(m) for m in moves]
    median_abs = statistics.median(abs_moves)
    max_abs = max(abs_moves)
    return {
        "data_available": True,
        "n_events": n,
        "median_abs_move": round(median_abs, 4),
        "mean_abs_move": round(sum(abs_moves) / n, 4),
        "max_abs_move": round(max_abs, 4),
        "p_move_gt_5pct": round(sum(1 for m in abs_moves if m > 0.05) / n, 3),
        "p_move_gt_10pct": round(sum(1 for m in abs_moves if m > 0.10) / n, 3),
        "last_move": round(moves[0], 4),
        "pead_bias": round(sum(moves) / n, 4),
        "magnitude_class": _classify(median_abs, max_abs),
        "moves": [round(m, 4) for m in moves],
    }


def compute_earnings_move_stats(symbol: str, ticker=None, lookback_quarters: int = 8) -> dict:
    """Compute the distribution of historical 1-day post-earnings moves.

    Joins past earnings dates (``ticker.earnings_dates``) with ~2y of daily
    price history. All network access is best-effort: any failure (including
    Yahoo rate limiting) yields ``{"data_available": False}`` so callers can
    abstain rather than crash.
    """
    result = {"symbol": symbol.upper(), "data_available": False}
    try:
        ticker = ticker or yf.Ticker(symbol)

        earnings = ticker.earnings_dates
        if earnings is None or earnings.empty:
            return result

        # Past announcements only, most-recent-first, capped to the lookback.
        now = datetime.now(_NY)
        past = earnings[earnings.index < now].sort_index(ascending=False)
        if past.empty:
            return result
        earnings_idx = list(past.index[:lookback_quarters])

        hist = ticker.history(period="2y")
        if hist is None or hist.empty or "Close" not in hist:
            return result

        moves = reaction_moves(earnings_idx, hist["Close"])
        stats = summarize_moves(moves)
        stats["symbol"] = symbol.upper()
        return stats
    except Exception as e:  # pragma: no cover - network/parse failures
        result["error"] = str(e)
        return result


def adaptive_earnings_gate(next_earnings_date, move_stats: dict | None = None, today=None) -> dict:
    """Decide whether imminent earnings should cap the recommendation.

    Combines proximity (days to the next report) with the symbol's historical
    move magnitude. A quiet name (median move <3%) only earns an advisory note;
    a high-gap name (median >7% or any single move >15%) caps a BUY to HOLD up
    to two weeks out. When move data is unavailable, falls back to a
    conservative proximity-only cap.

    The gate can only LOWER a fresh BUY to HOLD; it never raises a rating and
    never touches an existing HOLD/AVOID. It is a verdict cap, not a point
    adjustment — it does not modify the composite score. Note a PMCC sub-score
    may already embed its own earnings-proximity penalty, so for PMCC names this
    cap is an additional conservative safeguard layered on top (defense in
    depth), not the sole earnings adjustment.
    """
    inactive = {
        "active": False,
        "cap_to": None,
        "severity": "none",
        "days_to_earnings": None,
        "magnitude_class": None,
        "note": None,
    }

    e_date = _to_date(next_earnings_date)
    if e_date is None:
        return inactive

    today = today or datetime.now(_NY).date()
    days = (e_date - today).days
    if days < 0 or days > GATE_WINDOW_DAYS:
        return inactive

    move_stats = move_stats or {}
    available = bool(move_stats.get("data_available"))
    cls = move_stats.get("magnitude_class") if available else "unknown"
    if cls not in ("low", "moderate", "high"):
        cls = "unknown"  # treat a malformed/partial stats dict as unknown, not moderate
    median_abs = move_stats.get("median_abs_move")
    max_abs = move_stats.get("max_abs_move")

    if available and median_abs is not None:
        move_desc = f"historically moves +/-{median_abs * 100:.1f}% (median) on earnings"
        if max_abs is not None:
            move_desc += f", max {max_abs * 100:.0f}%"
    else:
        move_desc = "historical earnings-move data unavailable"

    if cls == "low":
        if days <= 3:
            cap_to, severity = None, "advisory"
        else:
            return inactive
    elif cls == "high":
        if days <= 14:
            cap_to, severity = "HOLD", "elevated"
        else:
            cap_to, severity = None, "caution"
    else:  # moderate or unknown
        if days <= 10:
            cap_to, severity = "HOLD", "caution"
        else:
            cap_to, severity = None, "advisory"

    # The note describes the risk only; whether the rating is actually capped is
    # decided by the caller and reflected in the recommendation field, so the
    # note never asserts an outcome that did not happen (e.g. on an AVOID name).
    when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    if cap_to:
        note = f"Earnings {when}: stock {move_desc} - elevated gap risk through the event."
    else:
        note = f"Earnings {when}: stock {move_desc} - monitor for gap risk."

    return {
        "active": True,
        "cap_to": cap_to,
        "severity": severity,
        "days_to_earnings": days,
        "magnitude_class": cls,
        "note": note,
    }

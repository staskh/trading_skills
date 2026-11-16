# ABOUTME: Tests for daily pivot levels and the entry classification built on them.
# ABOUTME: Unit tests use synthetic OHLC bars; the live test pulls real Yahoo data.

import pandas as pd
import pytest

from trading_skills.pivots import (
    classic_pivots,
    classify_entry,
    get_pivot_levels,
    pivot_status,
    session_pivots,
)


def _bars(rows):
    """Build a daily OHLC frame from (high, low, close) tuples on consecutive weekdays."""
    idx = pd.bdate_range("2026-10-01", periods=len(rows))
    return pd.DataFrame(
        {
            "Open": [c for _, _, c in rows],
            "High": [h for h, _, _ in rows],
            "Low": [lo for _, lo, _ in rows],
            "Close": [c for _, _, c in rows],
        },
        index=idx,
    )


def test_classic_pivots_floor_formula():
    levels = classic_pivots(high=110.0, low=90.0, close=100.0)
    assert levels == {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}


def test_session_pivots_use_prior_session_bar():
    bars = _bars([(110, 90, 100), (106, 98, 104), (108, 100, 102)])
    sessions = session_pivots(bars, sessions=2)
    assert [s["date"] for s in sessions] == ["2026-10-02", "2026-10-05"]
    # 2026-10-02 levels come from 2026-10-01 (110/90/100)
    assert sessions[0]["levels"]["P"] == 100.0
    assert sessions[0]["close"] == 104
    # 2026-10-05 levels come from 2026-10-02 (106/98/104): P = 308/3
    assert sessions[1]["levels"]["P"] == pytest.approx(102.6667, abs=1e-3)


def test_session_pivots_limited_by_available_history():
    bars = _bars([(110, 90, 100), (106, 98, 104)])
    assert len(session_pivots(bars, sessions=5)) == 1


def test_classify_near_support():
    current = {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}
    result = classify_entry(price=100.8, current=current, history=[], tolerance_pct=1.5)
    assert result["status"] == "near_support"
    assert result["nearest_support"] == {"level": "P", "price": 100.0}
    assert result["next_support"] == {"level": "S1", "price": 90.0}
    assert result["pct_above_support"] == pytest.approx(0.8)


def test_classify_neutral_between_levels():
    current = {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}
    result = classify_entry(price=105.0, current=current, history=[], tolerance_pct=1.5)
    assert result["status"] == "neutral"
    assert result["nearest_resistance"] == {"level": "R1", "price": 110.0}


def test_classify_chase_risk_uses_latest_breakout():
    current = {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}
    history = [
        {"date": "d1", "levels": {"R1": 104.0}, "high": 106, "low": 101, "close": 105},
        {"date": "d2", "levels": {"R1": 107.0}, "high": 112, "low": 106, "close": 111},
    ]
    result = classify_entry(price=112.0, current=current, history=history, tolerance_pct=1.5)
    assert result["status"] == "chase_risk"
    assert result["breakout"] == {"date": "d2", "level": 107.0, "retested": False}


def test_classify_chase_risk_off_hours_below_current_r1():
    """Off-hours the price is the last close, which can't exceed that bar's own R1."""
    current = {"P": 108.0, "R1": 112.0, "R2": 116.0, "S1": 104.0, "S2": 100.0}
    history = [
        {"date": "d1", "levels": {"R1": 100.0}, "high": 104, "low": 99, "close": 103},
        {"date": "d2", "levels": {"R1": 103.0}, "high": 110, "low": 104, "close": 109},
    ]
    result = classify_entry(price=109.0, current=current, history=history, tolerance_pct=1.5)
    assert result["status"] == "chase_risk"
    assert result["breakout"] == {"date": "d2", "level": 103.0, "retested": False}


def test_classify_retested_breakout_is_not_chase():
    current = {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}
    history = [
        {"date": "d1", "levels": {"R1": 104.0}, "high": 106, "low": 101, "close": 105},
        {"date": "d2", "levels": {"R1": 107.0}, "high": 106, "low": 103.5, "close": 105},
    ]
    result = classify_entry(price=111.0, current=current, history=history, tolerance_pct=1.5)
    assert result["status"] == "breakout_retested"
    assert result["breakout"] == {"date": "d1", "level": 104.0, "retested": True}


def test_classify_failed_breakout_falls_back_to_supports():
    """A breakout the price has since fallen below is not a chase."""
    current = {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}
    history = [
        {"date": "d1", "levels": {"R1": 104.0}, "high": 106, "low": 101, "close": 105},
    ]
    result = classify_entry(price=100.5, current=current, history=history, tolerance_pct=1.5)
    assert result["status"] == "near_support"
    assert result["breakout"] is None


def test_classify_live_break_above_current_r1():
    current = {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}
    result = classify_entry(price=111.0, current=current, history=[], tolerance_pct=1.5)
    assert result["status"] == "chase_risk"
    assert result["breakout"] == {"date": "current", "level": 110.0, "retested": False}


def test_classify_below_all_supports():
    current = {"P": 100.0, "R1": 110.0, "R2": 120.0, "S1": 90.0, "S2": 80.0}
    result = classify_entry(price=75.0, current=current, history=[], tolerance_pct=1.5)
    assert result["status"] == "below_supports"
    assert result["nearest_support"] is None


def test_get_pivot_levels_live():
    result = get_pivot_levels(["AAPL", "MSFT"], sessions=5)
    assert result["data_delay"] == "15min"
    assert "generated_at" in result
    assert [r["symbol"] for r in result["results"]] == ["AAPL", "MSFT"]
    for row in result["results"]:
        assert len(row["sessions"]) == 5
        assert row["price"] > 0
        assert set(row["current_levels"]) == {"P", "R1", "R2", "S1", "S2"}
        assert row["status"] in {
            "near_support",
            "neutral",
            "chase_risk",
            "breakout_retested",
            "below_supports",
        }


def test_get_pivot_levels_unknown_symbol_reports_error():
    result = get_pivot_levels(["ZZZZNOTREAL"], sessions=5)
    assert "error" in result["results"][0]


def _ten_bars():
    return _bars(
        [
            (110, 90, 100),
            (112, 95, 105),
            (115, 100, 110),
            (118, 104, 108),
            (120, 106, 115),
            (119, 108, 112),
            (122, 110, 118),
            (125, 114, 120),
            (124, 116, 119),
            (126, 117, 121),
        ]
    )


def test_pivot_status_matches_get_pivot_levels_body():
    bars = _ten_bars()
    last = bars.iloc[-1]
    current = classic_pivots(last["High"], last["Low"], last["Close"])
    history = session_pivots(bars, 5)
    price = round(float(last["Close"]), 4)
    expected = {
        "price": price,
        "current_levels": current,
        "sessions": history,
        **classify_entry(price, current, history, 1.5),
    }
    assert pivot_status(bars) == expected


def test_pivot_status_drop_today_partial_uses_last_bar_for_price_only():
    bars = _ten_bars()
    completed = bars.iloc[:-1]
    prior = completed.iloc[-1]
    current = classic_pivots(prior["High"], prior["Low"], prior["Close"])
    history = session_pivots(completed, 5)
    price = round(float(bars["Close"].iloc[-1]), 4)
    expected = {
        "price": price,
        "current_levels": current,
        "sessions": history,
        **classify_entry(price, current, history, 1.5),
    }
    result = pivot_status(bars, drop_today_partial=True)
    assert result == expected
    assert result["sessions"][-1]["date"] == completed.index[-1].strftime("%Y-%m-%d")

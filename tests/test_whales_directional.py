# ABOUTME: Unit tests for spot attachment and directional flow aggregation in whale hunting.
# ABOUTME: Verifies per-trade spot matching, break-even distance, and the 1.5% directional filter.

from zoneinfo import ZoneInfo

import pandas as pd

from trading_skills.massive.whales import attach_spot, directional_flow

_NY = ZoneInfo("America/New_York")


def _ts(hms):
    return pd.Timestamp(f"2026-11-02 {hms}", tz=_NY)


def _whales_df(records):
    defaults = {
        "ticker": "AAPL261106C00300000",
        "type": "call",
        "strike": 300.0,
        "expiry": "2026-11-06",
        "close": 1.0,
        "volume": 10,
        "open_interest": 100,
        "transactions": 1,
        "invested": 1_000.0,
        "break_even": 301.0,
        "reason": "z_score",
    }
    return pd.DataFrame([{**defaults, **r} for r in records])


def _spot_bars(records):
    return pd.DataFrame([{"timestamp": _ts(t), "spot": s} for t, s in records])


class TestAttachSpot:
    def test_uses_latest_spot_at_or_before_trade(self):
        whales = _whales_df([{"timestamp": _ts("10:00:05")}, {"timestamp": _ts("10:00:10")}])
        bars = _spot_bars([("10:00:00", 100.0), ("10:00:05", 101.0), ("10:00:08", 102.0)])
        result = attach_spot(whales, bars)
        assert list(result["spot"]) == [101.0, 102.0]

    def test_pct_from_spot_is_break_even_distance_in_percent(self):
        whales = _whales_df(
            [
                {"timestamp": _ts("10:00:00"), "break_even": 103.0},
                {"timestamp": _ts("10:00:00"), "break_even": 98.5},
            ]
        )
        bars = _spot_bars([("10:00:00", 100.0)])
        result = attach_spot(whales, bars)
        assert list(result["pct_from_spot"]) == [3.0, -1.5]

    def test_columns_placed_after_strike_and_break_even(self):
        whales = _whales_df([{"timestamp": _ts("10:00:00")}])
        bars = _spot_bars([("10:00:00", 100.0)])
        cols = list(attach_spot(whales, bars).columns)
        assert cols[cols.index("strike") + 1] == "spot"
        assert cols[cols.index("break_even") + 1] == "pct_from_spot"

    def test_trade_before_first_spot_bar_has_no_spot(self):
        whales = _whales_df([{"timestamp": _ts("09:30:00")}])
        bars = _spot_bars([("10:00:00", 100.0)])
        result = attach_spot(whales, bars)
        assert pd.isna(result.iloc[0]["spot"])
        assert pd.isna(result.iloc[0]["pct_from_spot"])

    def test_preserves_original_row_order(self):
        whales = _whales_df(
            [
                {"timestamp": _ts("10:00:10"), "ticker": "late"},
                {"timestamp": _ts("10:00:00"), "ticker": "early"},
            ]
        )
        bars = _spot_bars([("10:00:00", 100.0), ("10:00:10", 110.0)])
        result = attach_spot(whales, bars)
        assert list(result["ticker"]) == ["late", "early"]
        assert list(result["spot"]) == [110.0, 100.0]


class TestDirectionalFlow:
    def test_counts_only_calls_and_puts_beyond_threshold(self):
        whales = [
            {"type": "call", "invested": 100.0, "pct_from_spot": 1.5},
            {"type": "call", "invested": 200.0, "pct_from_spot": 1.49},
            {"type": "call", "invested": 400.0, "pct_from_spot": -5.0},
            {"type": "put", "invested": 50.0, "pct_from_spot": -2.0},
            {"type": "put", "invested": 75.0, "pct_from_spot": -1.0},
            {"type": "put", "invested": 300.0, "pct_from_spot": 4.0},
        ]
        result = directional_flow(whales)
        assert result["directional_call_invested"] == 100.0
        assert result["directional_put_invested"] == 50.0
        assert result["directional_call_put_ratio"] == 2.0

    def test_missing_pct_from_spot_is_ignored(self):
        whales = [
            {"type": "call", "invested": 100.0, "pct_from_spot": None},
            {"type": "put", "invested": 50.0, "pct_from_spot": float("nan")},
        ]
        result = directional_flow(whales)
        assert result["directional_call_invested"] == 0
        assert result["directional_put_invested"] == 0

    def test_ratio_is_none_without_directional_puts(self):
        whales = [{"type": "call", "invested": 100.0, "pct_from_spot": 3.0}]
        assert directional_flow(whales)["directional_call_put_ratio"] is None

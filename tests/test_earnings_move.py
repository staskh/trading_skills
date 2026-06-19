# ABOUTME: Tests for the historical earnings-move helper and the adaptive earnings gate.
# ABOUTME: Pure-function tests (no network) plus gate integration with compute_recommendation.

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from trading_skills.earnings_move import (
    adaptive_earnings_gate,
    reaction_moves,
    summarize_moves,
)
from trading_skills.report import compute_recommendation

_NY = ZoneInfo("America/New_York")


def _closes(pairs):
    """Build a close Series from (date_str, value) pairs."""
    idx = pd.to_datetime([d for d, _ in pairs])
    return pd.Series([v for _, v in pairs], index=idx)


def _ny_today():
    return datetime.now(_NY).date()


def _in_days(n):
    return (_ny_today() + timedelta(days=n)).isoformat()


class TestReactionMoves:
    def test_after_close_report_uses_next_session(self):
        # Earnings reported AMC on Jan 6 -> reaction shows up Jan 7 (+10%).
        closes = _closes(
            [
                ("2025-01-02", 100),
                ("2025-01-03", 100),
                ("2025-01-06", 100),
                ("2025-01-07", 110),
                ("2025-01-08", 110),
            ]
        )
        moves = reaction_moves(["2025-01-06"], closes)
        assert len(moves) == 1
        assert abs(moves[0] - 0.10) < 1e-6

    def test_before_open_report_uses_same_session(self):
        # Earnings reported BMO on Jan 7 -> reaction is the Jan 7 close (-10%).
        closes = _closes(
            [
                ("2025-01-02", 100),
                ("2025-01-03", 100),
                ("2025-01-06", 100),
                ("2025-01-07", 90),
                ("2025-01-08", 90),
            ]
        )
        moves = reaction_moves(["2025-01-07"], closes)
        assert len(moves) == 1
        assert abs(moves[0] + 0.10) < 1e-6

    def test_skips_event_without_prior_session(self):
        closes = _closes([("2025-01-02", 100), ("2025-01-03", 101)])
        # Earnings before the first available session -> unmeasurable, skipped.
        assert reaction_moves(["2024-12-01"], closes) == []

    def test_preserves_input_order(self):
        closes = _closes(
            [
                ("2025-01-02", 100),
                ("2025-01-03", 100),
                ("2025-01-06", 100),
                ("2025-01-07", 110),
                ("2025-01-08", 95),
            ]
        )
        moves = reaction_moves(["2025-01-07", "2025-01-06"], closes)
        assert len(moves) == 2

    def test_empty_series_returns_empty(self):
        assert reaction_moves(["2025-01-06"], _closes([])) == []

    def test_skips_nan_close_in_window(self):
        # A NaN close adjacent to the event must not poison the distribution.
        closes = _closes(
            [
                ("2025-01-02", 100),
                ("2025-01-03", 100),
                ("2025-01-06", 100),
                ("2025-01-07", float("nan")),
                ("2025-01-08", 110),
            ]
        )
        assert reaction_moves(["2025-01-06"], closes) == []

    def test_skips_event_on_final_session(self):
        # Earnings on the last available bar: an after-close gap would land on a
        # session not yet in history, so the event is not measurable -> skipped.
        closes = _closes([("2025-01-02", 100), ("2025-01-03", 100), ("2025-01-06", 120)])
        assert reaction_moves(["2025-01-06"], closes) == []

    def test_handles_unsorted_index(self):
        pairs = [
            ("2025-01-08", 110),
            ("2025-01-02", 100),
            ("2025-01-07", 110),
            ("2025-01-06", 100),
            ("2025-01-03", 100),
        ]
        moves = reaction_moves(["2025-01-06"], _closes(pairs))
        assert len(moves) == 1
        assert abs(moves[0] - 0.10) < 1e-6


class TestSummarizeMoves:
    def test_insufficient_events(self):
        out = summarize_moves([0.05])
        assert out["data_available"] is False
        assert out["n_events"] == 1

    def test_filters_non_finite(self):
        out = summarize_moves([0.05, float("nan"), -0.04, 0.06])
        assert out["data_available"] is True
        assert out["n_events"] == 3  # NaN dropped before stats
        assert out["magnitude_class"] == "moderate"

    def test_low_magnitude_class(self):
        out = summarize_moves([0.01, -0.02, 0.015, -0.025])
        assert out["data_available"] is True
        assert out["magnitude_class"] == "low"
        assert out["n_events"] == 4

    def test_moderate_magnitude_class(self):
        out = summarize_moves([0.04, -0.05, 0.06, -0.045])
        assert out["magnitude_class"] == "moderate"

    def test_high_by_median(self):
        out = summarize_moves([0.08, -0.09, 0.07, -0.10])
        assert out["magnitude_class"] == "high"

    def test_high_by_tail(self):
        # Median is small but a single 16% gap is high-gap tail risk.
        out = summarize_moves([0.02, -0.03, 0.16, -0.02])
        assert out["magnitude_class"] == "high"

    def test_stats_fields(self):
        moves = [0.10, -0.05, 0.12, -0.08]
        out = summarize_moves(moves)
        assert out["last_move"] == 0.10  # most-recent-first
        assert out["max_abs_move"] == 0.12
        # |moves| = [0.10, 0.05, 0.12, 0.08]; strict ">" thresholds.
        assert out["p_move_gt_5pct"] == 0.75  # 0.10, 0.12, 0.08
        assert out["p_move_gt_10pct"] == 0.25  # only 0.12


class TestAdaptiveEarningsGate:
    HIGH = {
        "data_available": True,
        "magnitude_class": "high",
        "median_abs_move": 0.09,
        "max_abs_move": 0.18,
    }
    MOD = {
        "data_available": True,
        "magnitude_class": "moderate",
        "median_abs_move": 0.05,
        "max_abs_move": 0.08,
    }
    LOW = {
        "data_available": True,
        "magnitude_class": "low",
        "median_abs_move": 0.018,
        "max_abs_move": 0.04,
    }
    UNKNOWN = {"data_available": False}

    def _at(self, days):
        return date(2025, 6, 18) + timedelta(days=days)

    def test_no_earnings_date_inactive(self):
        g = adaptive_earnings_gate(None, self.HIGH, today=date(2025, 6, 18))
        assert g["active"] is False

    def test_far_earnings_inactive(self):
        g = adaptive_earnings_gate(self._at(40).isoformat(), self.HIGH, today=date(2025, 6, 18))
        assert g["active"] is False

    def test_passed_earnings_inactive(self):
        g = adaptive_earnings_gate(self._at(-2).isoformat(), self.HIGH, today=date(2025, 6, 18))
        assert g["active"] is False

    def test_high_near_caps_hold(self):
        g = adaptive_earnings_gate(self._at(5).isoformat(), self.HIGH, today=date(2025, 6, 18))
        assert g["active"] and g["cap_to"] == "HOLD"
        assert g["severity"] == "elevated"

    def test_high_far_within_window_advises_no_cap(self):
        g = adaptive_earnings_gate(self._at(18).isoformat(), self.HIGH, today=date(2025, 6, 18))
        assert g["active"] and g["cap_to"] is None

    def test_moderate_near_caps(self):
        g = adaptive_earnings_gate(self._at(8).isoformat(), self.MOD, today=date(2025, 6, 18))
        assert g["cap_to"] == "HOLD"

    def test_moderate_mid_window_no_cap(self):
        g = adaptive_earnings_gate(self._at(15).isoformat(), self.MOD, today=date(2025, 6, 18))
        assert g["active"] and g["cap_to"] is None

    def test_low_very_near_advises_no_cap(self):
        g = adaptive_earnings_gate(self._at(2).isoformat(), self.LOW, today=date(2025, 6, 18))
        assert g["active"] and g["cap_to"] is None

    def test_low_not_imminent_inactive(self):
        g = adaptive_earnings_gate(self._at(8).isoformat(), self.LOW, today=date(2025, 6, 18))
        assert g["active"] is False

    def test_unknown_near_caps_conservatively(self):
        g = adaptive_earnings_gate(self._at(5).isoformat(), self.UNKNOWN, today=date(2025, 6, 18))
        assert g["cap_to"] == "HOLD"
        assert g["magnitude_class"] == "unknown"

    def test_unknown_missing_stats_dict(self):
        g = adaptive_earnings_gate(self._at(5).isoformat(), None, today=date(2025, 6, 18))
        assert g["cap_to"] == "HOLD"

    def test_note_present_when_active(self):
        g = adaptive_earnings_gate(self._at(5).isoformat(), self.HIGH, today=date(2025, 6, 18))
        assert "Earnings" in g["note"]

    def test_available_but_missing_class_treated_as_unknown(self):
        g = adaptive_earnings_gate(
            self._at(5).isoformat(),
            {"data_available": True, "median_abs_move": 0.05},  # no magnitude_class
            today=date(2025, 6, 18),
        )
        assert g["magnitude_class"] == "unknown"
        assert g["cap_to"] == "HOLD"


class TestComputeRecommendationGate:
    """Gate integration: an imminent-earnings BUY caps to HOLD by gap risk."""

    def _buy_data(self, next_earnings=None, earnings_move="__missing__"):
        data = {
            "bullish": {"score": 7.0, "rsi": 55, "adx": 30, "next_earnings": next_earnings},
            "pmcc": {"pmcc_score": 10, "iv_pct": 35},
            "fundamentals": {"info": {"forwardPE": 12, "returnOnEquity": 0.25}},
            "piotroski": {"score": 8},
        }
        if earnings_move != "__missing__":
            data["earnings_move"] = earnings_move
        return data

    HIGH = {
        "data_available": True,
        "magnitude_class": "high",
        "median_abs_move": 0.09,
        "max_abs_move": 0.18,
    }
    LOW = {
        "data_available": True,
        "magnitude_class": "low",
        "median_abs_move": 0.018,
        "max_abs_move": 0.04,
    }

    def test_no_earnings_stays_buy(self):
        result = compute_recommendation(self._buy_data())
        assert result["recommendation_level"] == "positive"
        assert result["earnings_gate"]["active"] is False

    def test_high_move_near_earnings_caps_to_hold(self):
        result = compute_recommendation(
            self._buy_data(next_earnings=_in_days(5), earnings_move=self.HIGH)
        )
        assert result["recommendation_level"] == "neutral"
        assert result["recommendation"] == "HOLD / MONITOR"
        assert any("Earnings" in r for r in result["risks"])

    def test_high_move_far_earnings_stays_buy(self):
        result = compute_recommendation(
            self._buy_data(next_earnings=_in_days(40), earnings_move=self.HIGH)
        )
        assert result["recommendation_level"] == "positive"

    def test_low_move_near_earnings_stays_buy(self):
        # Low-volatility name 5 days out -> gate inactive, BUY preserved.
        result = compute_recommendation(
            self._buy_data(next_earnings=_in_days(5), earnings_move=self.LOW)
        )
        assert result["recommendation_level"] == "positive"

    def test_low_move_very_near_advises_but_keeps_buy(self):
        result = compute_recommendation(
            self._buy_data(next_earnings=_in_days(2), earnings_move=self.LOW)
        )
        assert result["recommendation_level"] == "positive"
        assert any("Earnings" in r for r in result["risks"])

    def test_missing_move_data_caps_conservatively(self):
        # No earnings_move data, but earnings imminent -> conservative cap.
        result = compute_recommendation(self._buy_data(next_earnings=_in_days(5)))
        assert result["recommendation_level"] == "neutral"

    def test_weak_stock_near_earnings_not_falsely_capped(self):
        # An AVOID name must stay AVOID and the note must not claim a HOLD cap.
        data = {
            "bullish": {"score": 1.5, "rsi": 75, "adx": 15, "next_earnings": _in_days(5)},
            "pmcc": {"pmcc_score": 0},
            "fundamentals": {"info": {"forwardPE": 50}},
            "piotroski": {"score": 2},
            "earnings_move": self.HIGH,
        }
        result = compute_recommendation(data)
        assert result["recommendation_level"] == "negative"
        note = " ".join(result["risks"])
        assert "Earnings" in note
        assert "capping" not in note.lower()

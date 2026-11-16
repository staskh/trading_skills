# ABOUTME: Unit tests for open-interest walls and whale call/put totals in whale hunting.
# ABOUTME: Verifies per-strike OI summing, put/call ratios, walls, and missing-value handling.

import math

from trading_skills.massive.whales import open_interest_walls, whale_totals


def _row(type_, strike, oi):
    return {"type": type_, "strike": strike, "openInterest": oi}


class TestOpenInterestWalls:
    def test_sums_oi_per_strike_across_expiries(self):
        rows = [
            _row("call", 100.0, 500),
            _row("call", 100.0, 700),  # same strike, another expiry
            _row("call", 110.0, 1000),
            _row("put", 90.0, 300),
            _row("put", 95.0, 200),
        ]
        result = open_interest_walls(rows)
        assert result["call_oi"] == 2200
        assert result["put_oi"] == 500
        assert result["put_call_oi_ratio"] == round(500 / 2200, 4)
        assert result["call_wall"] == {"strike": 100.0, "open_interest": 1200}
        assert result["put_wall"] == {"strike": 90.0, "open_interest": 300}

    def test_ignores_missing_oi(self):
        rows = [_row("call", 100.0, math.nan), _row("call", 105.0, None), _row("call", 110.0, 50)]
        result = open_interest_walls(rows)
        assert result["call_oi"] == 50
        assert result["call_wall"] == {"strike": 110.0, "open_interest": 50}

    def test_tie_picks_lowest_strike(self):
        rows = [_row("put", 95.0, 100), _row("put", 90.0, 100)]
        assert open_interest_walls(rows)["put_wall"] == {"strike": 90.0, "open_interest": 100}

    def test_side_without_oi_has_no_wall_and_no_ratio(self):
        result = open_interest_walls([_row("put", 90.0, 100), _row("call", 100.0, 0)])
        assert result["call_oi"] == 0
        assert result["call_wall"] is None
        assert result["put_call_oi_ratio"] is None

    def test_empty_rows(self):
        assert open_interest_walls([]) == {
            "call_oi": 0,
            "put_oi": 0,
            "put_call_oi_ratio": None,
            "call_wall": None,
            "put_wall": None,
        }


def _whale(type_, strike, invested):
    return {"type": type_, "strike": strike, "invested": invested}


class TestWhaleTotals:
    def test_totals_ratio_and_walls(self):
        whales = [
            _whale("call", 100.0, 1_000_000.0),
            _whale("call", 100.0, 500_000.0),
            _whale("call", 120.0, 1_200_000.0),
            _whale("put", 80.0, 900_000.0),
        ]
        result = whale_totals(whales)
        assert result["call_invested"] == 2_700_000.0
        assert result["put_invested"] == 900_000.0
        assert result["put_call_ratio"] == round(900_000 / 2_700_000, 4)
        assert result["call_wall"] == {"strike": 100.0, "invested": 1_500_000.0}
        assert result["put_wall"] == {"strike": 80.0, "invested": 900_000.0}

    def test_skips_missing_invested(self):
        result = whale_totals([_whale("call", 100.0, None), _whale("call", 105.0, 10.0)])
        assert result["call_invested"] == 10.0
        assert result["call_wall"] == {"strike": 105.0, "invested": 10.0}

    def test_no_calls_means_no_ratio(self):
        result = whale_totals([_whale("put", 80.0, 10.0)])
        assert result["put_call_ratio"] is None
        assert result["call_wall"] is None

    def test_empty(self):
        assert whale_totals([]) == {
            "call_invested": 0,
            "put_invested": 0,
            "put_call_ratio": None,
            "call_wall": None,
            "put_wall": None,
        }

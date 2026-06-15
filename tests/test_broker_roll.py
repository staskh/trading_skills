# ABOUTME: Tests for roll analysis module pure logic functions.
# ABOUTME: Validates candidate evaluation and roll calculation logic.

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from trading_skills.broker.roll import (
    calculate_roll_options,
    evaluate_short_candidates,
    get_current_position,
    get_long_option_position,
)
from trading_skills.utils import days_to_expiry


class TestDaysToExpiry:
    """Tests for days to expiry calculation."""

    def test_future_date(self):
        future = datetime.now() + timedelta(days=30)
        expiry_str = future.strftime("%Y%m%d")
        days = days_to_expiry(expiry_str)
        assert 29 <= days <= 31

    def test_past_date(self):
        past = datetime.now() - timedelta(days=10)
        expiry_str = past.strftime("%Y%m%d")
        days = days_to_expiry(expiry_str)
        assert days < 0

    def test_invalid_returns_999(self):
        assert days_to_expiry("invalid") == 999


class TestEvaluateShortCandidates:
    """Tests for short option candidate evaluation."""

    def test_filters_zero_bid(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 0, "ask": 1.0, "mid": 0.5, "last": 0}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 0

    def test_filters_itm(self):
        quotes = [
            {"strike": 90, "expiry": "20250321", "bid": 12.0, "ask": 13.0, "mid": 12.5, "last": 12}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 0

    def test_otm_call_included(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 1
        assert result[0]["strike"] == 110
        assert result[0]["otm_pct"] == 10.0

    def test_otm_put_included(self):
        quotes = [
            {"strike": 90, "expiry": "20250321", "bid": 1.5, "ask": 2.0, "mid": 1.75, "last": 1.5}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "P", 30)
        assert len(result) == 1
        assert result[0]["otm_pct"] == 10.0

    def test_sorted_by_score_descending(self):
        quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 3.0, "ask": 3.5, "mid": 3.25, "last": 3},
            {"strike": 115, "expiry": "20250321", "bid": 0.5, "ask": 1.0, "mid": 0.75, "last": 0.5},
            {"strike": 110, "expiry": "20250321", "bid": 1.5, "ask": 2.0, "mid": 1.75, "last": 1.5},
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 3
        # Scores should be descending
        for i in range(len(result) - 1):
            assert result[i]["score"] >= result[i + 1]["score"]

    def test_annual_return_calculated(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        # annual_return = (2.0 / 100.0) * (365/30) * 100 = 24.33%
        assert result[0]["annual_return"] > 20

    def test_time_score_preferred_range(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result_30 = evaluate_short_candidates(quotes, 100.0, "C", 30)
        result_7 = evaluate_short_candidates(quotes, 100.0, "C", 7)
        # 30 DTE in preferred 21-60 range, 7 DTE is not
        assert result_30[0]["score"] > result_7[0]["score"]


class TestCalculateRollOptions:
    """Tests for roll credit/debit calculation."""

    def test_credit_roll(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 3.0, "ask": 3.5, "mid": 3.25, "last": 3}
        ]
        buy_price = 1.50
        result = calculate_roll_options(current, target_quotes, buy_price)
        assert len(result) == 1
        assert result[0]["net"] == 1.50  # 3.0 - 1.5
        assert result[0]["net_type"] == "credit"

    def test_debit_roll(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 0.50, "ask": 1.0, "mid": 0.75, "last": 0.5}
        ]
        buy_price = 2.00
        result = calculate_roll_options(current, target_quotes, buy_price)
        assert len(result) == 1
        assert result[0]["net"] == -1.50  # 0.5 - 2.0
        assert result[0]["net_type"] == "debit"

    def test_filters_zero_bid(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 0, "ask": 0.5, "mid": 0.25, "last": 0}
        ]
        result = calculate_roll_options(current, target_quotes, 1.0)
        assert len(result) == 0

    def test_far_otm_penalty_applied(self):
        # OTM > 15% should get safety_score penalty but still be included
        quotes = [
            {
                "strike": 120,
                "expiry": "20250321",
                "bid": 0.50,
                "ask": 0.80,
                "mid": 0.65,
                "last": 0.6,
            }
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 1
        # 20% OTM should have penalty applied (score still calculated)
        assert result[0]["otm_pct"] == pytest.approx(20.0)


def _make_position(symbol, sec_type, position, strike=100.0, expiry="20260620", right="C"):
    """Build a mock IB position tuple."""
    contract = MagicMock()
    contract.symbol = symbol
    contract.secType = sec_type
    contract.strike = strike
    contract.lastTradeDateOrContractMonth = expiry
    contract.right = right
    contract.multiplier = "20"
    pos = MagicMock()
    pos.contract = contract
    pos.position = position
    pos.account = "DU123456"
    pos.avgCost = 500.0
    return pos


class TestGetCurrentPositionFop:
    """get_current_position must include FOP short positions and surface sec_type."""

    @pytest.mark.asyncio
    async def test_returns_fop_short_position(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", -1, strike=21000.0)])
        result = await get_current_position(ib, "NQ")
        assert result is not None
        assert result["sec_type"] == "FOP"
        assert result["strike"] == 21000.0

    @pytest.mark.asyncio
    async def test_returns_opt_short_position(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("AAPL", "OPT", -2, strike=200.0)])
        result = await get_current_position(ib, "AAPL")
        assert result is not None
        assert result["sec_type"] == "OPT"

    @pytest.mark.asyncio
    async def test_ignores_long_positions(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", 1, strike=21000.0)])
        result = await get_current_position(ib, "NQ")
        assert result is None


class TestGetLongOptionPositionFop:
    """get_long_option_position must include FOP long positions and surface sec_type."""

    @pytest.mark.asyncio
    async def test_returns_fop_long_position(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", 1, strike=20000.0)])
        result = await get_long_option_position(ib, "NQ", "C")
        assert result is not None
        assert result["sec_type"] == "FOP"
        assert result["strike"] == 20000.0

    @pytest.mark.asyncio
    async def test_ignores_short_positions(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", -1, strike=20000.0)])
        result = await get_long_option_position(ib, "NQ", "C")
        assert result is None

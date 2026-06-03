# ABOUTME: Tests for roll analysis module pure logic functions.
# ABOUTME: Validates candidate evaluation and roll calculation logic.

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_skills.broker.roll import (
    _resolve_fop_contracts,
    calculate_roll_options,
    evaluate_short_candidates,
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


def _fop_detail(trading_class: str, con_id: int):
    """Build a mock ContractDetails whose .contract carries a tradingClass + conId."""
    contract = MagicMock()
    contract.tradingClass = trading_class
    contract.conId = con_id
    detail = MagicMock()
    detail.contract = contract
    return detail


class TestResolveFopContracts:
    """Regression tests for FOP tradingClass disambiguation (roll-fop-ambiguity bug)."""

    @pytest.mark.asyncio
    async def test_prefers_standard_monthly_class(self):
        # Same (expiry, strike) returns both the standard NQ class and a Q3D weekly.
        # qualifyContracts would choke on this; _resolve_fop_contracts must pick NQ.
        ib = MagicMock()
        ib.reqContractDetailsAsync = AsyncMock(
            return_value=[_fop_detail("Q3D", 888), _fop_detail("NQ", 877)]
        )
        resolved = await _resolve_fop_contracts(ib, "NQ", "20260618", [31300], "C")
        assert len(resolved) == 1
        assert resolved[0].tradingClass == "NQ"
        assert resolved[0].conId == 877

    @pytest.mark.asyncio
    async def test_falls_back_to_only_class(self):
        # A weekly/daily expiry (no standard NQ contract) must still resolve.
        ib = MagicMock()
        ib.reqContractDetailsAsync = AsyncMock(return_value=[_fop_detail("Q2D", 555)])
        resolved = await _resolve_fop_contracts(ib, "NQ", "20260611", [31300], "C")
        assert len(resolved) == 1
        assert resolved[0].conId == 555

    @pytest.mark.asyncio
    async def test_skips_strike_with_no_contract(self):
        ib = MagicMock()
        ib.reqContractDetailsAsync = AsyncMock(return_value=[])
        resolved = await _resolve_fop_contracts(ib, "NQ", "20260618", [99999], "C")
        assert resolved == []

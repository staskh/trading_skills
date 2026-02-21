# ABOUTME: Tests for spread analysis module using real Yahoo Finance data.
# ABOUTME: Validates vertical, straddle, strangle, and iron condor strategies.

import math

import pytest
import yfinance as yf

from trading_skills.options import get_expiries
from trading_skills.spreads import (
    analyze_iron_condor,
    analyze_straddle,
    analyze_strangle,
    analyze_vertical,
)
from trading_skills.utils import get_current_price


def _round_strike(price, step=5):
    """Round price to nearest strike increment."""
    return round(math.floor(price / step) * step, 2)


@pytest.fixture(scope="module")
def aapl_expiry():
    """Get first AAPL expiry for spread tests."""
    expiries = get_expiries("AAPL")
    assert len(expiries) > 0
    return expiries[0]


@pytest.fixture(scope="module")
def aapl_atm():
    """Get AAPL current price rounded to nearest strike."""
    info = yf.Ticker("AAPL").info
    price = get_current_price(info)
    return _round_strike(price)


class TestAnalyzeVertical:
    """Tests for vertical spread analysis."""

    def test_bull_call_spread(self, aapl_expiry, aapl_atm):
        result = analyze_vertical("AAPL", aapl_expiry, "call", aapl_atm, aapl_atm + 10)
        assert result["symbol"] == "AAPL"
        assert "Vertical" in result["strategy"]
        assert len(result["legs"]) == 2
        assert "max_profit" in result
        assert "max_loss" in result
        assert "breakeven" in result

    def test_bear_put_spread(self, aapl_expiry, aapl_atm):
        result = analyze_vertical("AAPL", aapl_expiry, "put", aapl_atm + 10, aapl_atm)
        assert result["symbol"] == "AAPL"
        assert len(result["legs"]) == 2

    def test_invalid_strikes(self, aapl_expiry):
        result = analyze_vertical("AAPL", aapl_expiry, "call", 9999.0, 9998.0)
        assert "error" in result


class TestAnalyzeStraddle:
    """Tests for straddle analysis."""

    def test_straddle(self, aapl_expiry, aapl_atm):
        result = analyze_straddle("AAPL", aapl_expiry, aapl_atm)
        assert result["strategy"] == "Long Straddle"
        assert len(result["legs"]) == 2
        assert "breakeven_up" in result
        assert "breakeven_down" in result
        assert result["breakeven_up"] > result["breakeven_down"]

    def test_straddle_cost(self, aapl_expiry, aapl_atm):
        result = analyze_straddle("AAPL", aapl_expiry, aapl_atm)
        assert result["total_cost"] > 0
        assert result["max_loss"] == result["total_cost"]


class TestAnalyzeStrangle:
    """Tests for strangle analysis."""

    def test_strangle(self, aapl_expiry, aapl_atm):
        result = analyze_strangle("AAPL", aapl_expiry, aapl_atm - 10, aapl_atm + 10)
        assert result["strategy"] == "Long Strangle"
        assert len(result["legs"]) == 2
        assert "breakeven_up" in result
        assert "breakeven_down" in result


class TestAnalyzeIronCondor:
    """Tests for iron condor analysis."""

    def test_iron_condor(self, aapl_expiry, aapl_atm):
        result = analyze_iron_condor(
            "AAPL",
            aapl_expiry,
            put_long=aapl_atm - 20,
            put_short=aapl_atm - 10,
            call_short=aapl_atm + 10,
            call_long=aapl_atm + 20,
        )
        assert result["strategy"] == "Iron Condor"
        assert len(result["legs"]) == 4
        assert "net_credit" in result
        assert "breakeven_up" in result
        assert "breakeven_down" in result

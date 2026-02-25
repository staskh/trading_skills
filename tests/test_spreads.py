# ABOUTME: Tests for spread analysis module using real Yahoo Finance data.
# ABOUTME: Validates vertical, straddle, strangle, and iron condor strategies.

import pytest
import yfinance as yf

from trading_skills.spreads import (
    analyze_iron_condor,
    analyze_straddle,
    analyze_strangle,
    analyze_vertical,
)
from trading_skills.utils import get_current_price


@pytest.fixture(scope="module")
def aapl_ticker():
    """Shared AAPL ticker to avoid redundant API calls."""
    return yf.Ticker("AAPL")


@pytest.fixture(scope="module")
def aapl_expiry(aapl_ticker):
    """Get AAPL expiry ~30 days out for liquid options with time value."""
    from datetime import datetime, timedelta

    min_date = (datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d")
    expiries = aapl_ticker.options
    future = [e for e in expiries if e >= min_date]
    assert len(future) > 0, f"No AAPL expiry >= {min_date}"
    return future[0]


@pytest.fixture(scope="module")
def aapl_chain(aapl_ticker, aapl_expiry):
    """Get sorted strikes from actual AAPL option chain."""
    price = get_current_price(aapl_ticker.info)
    chain = aapl_ticker.option_chain(aapl_expiry)
    strikes = sorted(chain.calls["strike"].unique())
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - price))
    return {"strikes": strikes, "atm_idx": atm_idx}


@pytest.fixture(scope="module")
def aapl_atm(aapl_chain):
    """ATM strike from actual chain."""
    return aapl_chain["strikes"][aapl_chain["atm_idx"]]


class TestAnalyzeVertical:
    """Tests for vertical spread analysis."""

    def test_bull_call_spread(self, aapl_expiry, aapl_chain):
        s = aapl_chain["strikes"]
        i = aapl_chain["atm_idx"]
        result = analyze_vertical("AAPL", aapl_expiry, "call", s[i], s[i + 1])
        assert result["symbol"] == "AAPL"
        assert "Vertical" in result["strategy"]
        assert len(result["legs"]) == 2
        assert "max_profit" in result
        assert "max_loss" in result
        assert "breakeven" in result

    def test_bear_put_spread(self, aapl_expiry, aapl_chain):
        s = aapl_chain["strikes"]
        i = aapl_chain["atm_idx"]
        result = analyze_vertical("AAPL", aapl_expiry, "put", s[i + 1], s[i])
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

    def test_strangle(self, aapl_expiry, aapl_chain):
        s = aapl_chain["strikes"]
        i = aapl_chain["atm_idx"]
        # OTM put (2 strikes below) and OTM call (2 strikes above)
        result = analyze_strangle("AAPL", aapl_expiry, s[i - 2], s[i + 2])
        assert result["strategy"] == "Long Strangle"
        assert len(result["legs"]) == 2
        assert "breakeven_up" in result
        assert "breakeven_down" in result


class TestAnalyzeIronCondor:
    """Tests for iron condor analysis."""

    def test_iron_condor(self, aapl_expiry, aapl_chain):
        s = aapl_chain["strikes"]
        i = aapl_chain["atm_idx"]
        # Wings: 4 strikes wide, body: 2 strikes from ATM
        result = analyze_iron_condor(
            "AAPL",
            aapl_expiry,
            put_long=s[i - 4],
            put_short=s[i - 2],
            call_short=s[i + 2],
            call_long=s[i + 4],
        )
        assert result["strategy"] == "Iron Condor"
        assert len(result["legs"]) == 4
        assert "net_credit" in result
        assert "breakeven_up" in result
        assert "breakeven_down" in result

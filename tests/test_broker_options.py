# ABOUTME: Tests for IB option chain module using real IBKR data.
# ABOUTME: Requires TWS or IB Gateway running locally on port 7496.

import asyncio

import pytest

from trading_skills.broker.options import get_expiries, get_option_chain


def run(coro):
    """Run async function synchronously."""
    return asyncio.run(coro)


class TestGetExpiries:
    """Tests for get_expiries with real IB data."""

    def test_valid_symbol_returns_list(self):
        result = run(get_expiries("AAPL"))
        assert result["success"] is True
        assert isinstance(result["expiries"], list)
        assert len(result["expiries"]) > 0

    def test_expiry_format_yyyymmdd(self):
        """IB expiries are YYYYMMDD strings."""
        result = run(get_expiries("AAPL"))
        for exp in result["expiries"][:3]:
            assert len(exp) == 8
            assert exp.isdigit()

    def test_invalid_symbol_returns_error(self):
        result = run(get_expiries("INVALIDXYZ123"))
        assert result["success"] is False
        assert "error" in result


class TestGetOptionChain:
    """Tests for get_option_chain with real IB data."""

    @pytest.fixture
    def aapl_expiry(self):
        result = run(get_expiries("AAPL"))
        assert result["success"] is True
        assert len(result["expiries"]) > 0
        return result["expiries"][0]

    def test_chain_structure(self, aapl_expiry):
        result = run(get_option_chain("AAPL", aapl_expiry))
        assert result["success"] is True
        assert result["symbol"] == "AAPL"
        assert result["source"] == "ibkr"
        assert result["expiry"] == aapl_expiry
        assert "calls" in result
        assert "puts" in result
        assert len(result["calls"]) > 0
        assert len(result["puts"]) > 0

    def test_option_fields(self, aapl_expiry):
        result = run(get_option_chain("AAPL", aapl_expiry))
        call = result["calls"][0]
        for field in ["strike", "bid", "ask", "lastPrice", "volume", "openInterest"]:
            assert field in call, f"Missing field: {field}"

    def test_has_underlying_price(self, aapl_expiry):
        result = run(get_option_chain("AAPL", aapl_expiry))
        assert result["underlying_price"] is not None
        assert result["underlying_price"] > 0

    def test_invalid_expiry(self):
        result = run(get_option_chain("AAPL", "20200101"))
        assert result["success"] is False or len(result.get("calls", [])) == 0

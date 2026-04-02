# ABOUTME: Tests for option chain module using real Yahoo Finance data.
# ABOUTME: Validates expiry listing and chain retrieval.

from datetime import date

import pytest

from trading_skills.options import get_expiries, get_option_chain, parse_option_ticker


class TestGetExpiries:
    """Tests for get_expiries with real data."""

    def test_valid_symbol_returns_list(self):
        expiries = get_expiries("AAPL")
        assert isinstance(expiries, list)
        assert len(expiries) > 0

    def test_expiry_format(self):
        """Expiries should be YYYY-MM-DD strings."""
        expiries = get_expiries("AAPL")
        for exp in expiries[:3]:
            assert len(exp) == 10
            assert exp[4] == "-" and exp[7] == "-"

    def test_invalid_symbol_returns_empty(self):
        expiries = get_expiries("INVALIDXYZ123")
        assert expiries == []


class TestGetOptionChain:
    """Tests for get_option_chain with real data."""

    @pytest.fixture
    def aapl_expiry(self):
        expiries = get_expiries("AAPL")
        assert len(expiries) > 0
        return expiries[0]

    def test_chain_structure(self, aapl_expiry):
        result = get_option_chain("AAPL", aapl_expiry)
        assert result["symbol"] == "AAPL"
        assert result["expiry"] == aapl_expiry
        assert "calls" in result
        assert "puts" in result
        assert len(result["calls"]) > 0
        assert len(result["puts"]) > 0

    def test_option_fields(self, aapl_expiry):
        result = get_option_chain("AAPL", aapl_expiry)
        call = result["calls"][0]
        for field in ["strike", "bid", "ask", "volume", "openInterest"]:
            assert field in call, f"Missing field: {field}"

    def test_has_underlying_price(self, aapl_expiry):
        result = get_option_chain("AAPL", aapl_expiry)
        assert result["underlying_price"] is not None
        assert result["underlying_price"] > 0

    def test_invalid_expiry(self):
        result = get_option_chain("AAPL", "2020-01-01")
        assert "error" in result


class TestParseOptionTicker:
    def test_yfinance_put(self):
        underlying, opt_type, strike, expiry = parse_option_ticker("NVDA260320P00170000")
        assert underlying == "NVDA"
        assert opt_type == "put"
        assert strike == 170.0
        assert expiry == date(2026, 3, 20)

    def test_yfinance_call(self):
        underlying, opt_type, strike, expiry = parse_option_ticker("AAPL260117C00230000")
        assert underlying == "AAPL"
        assert opt_type == "call"
        assert strike == 230.0
        assert expiry == date(2026, 1, 17)

    def test_polygon_prefix_stripped(self):
        underlying, opt_type, strike, expiry = parse_option_ticker("O:NVDA260320P00170000")
        assert underlying == "NVDA"
        assert opt_type == "put"
        assert strike == 170.0
        assert expiry == date(2026, 3, 20)

    def test_fractional_strike(self):
        _, _, strike, _ = parse_option_ticker("NVDA260316C00182500")
        assert strike == 182.5

    def test_long_underlying(self):
        underlying, _, strike, _ = parse_option_ticker("O:GOOGL260320C00200000")
        assert underlying == "GOOGL"
        assert strike == 200.0

    def test_seven_digit_date_format(self):
        """OCC adjusted symbology: YYYMMDD where YYY = year - 1900."""
        underlying, opt_type, strike, expiry = parse_option_ticker("O:BABA1250620C00045000")
        assert underlying == "BABA"
        assert opt_type == "call"
        assert strike == 45.0
        assert expiry == date(2025, 6, 20)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_option_ticker("TOOSHORT")

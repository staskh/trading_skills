# ABOUTME: Tests for fundamentals module using real Yahoo Finance data.
# ABOUTME: Validates financial data retrieval for various data types.

from unittest.mock import MagicMock, PropertyMock, patch

import pandas as pd

from trading_skills.fundamentals import get_fundamentals

MODULE = "trading_skills.fundamentals"


class TestGetFundamentals:
    """Tests for get_fundamentals with real data."""

    def test_info_type(self):
        result = get_fundamentals("AAPL", "info")
        assert result["symbol"] == "AAPL"
        assert "info" in result
        assert result["info"]["name"] is not None

    def test_info_key_fields(self):
        result = get_fundamentals("AAPL", "info")
        info = result["info"]
        for field in ["name", "sector", "marketCap", "trailingPE", "eps"]:
            assert field in info, f"Missing field: {field}"

    def test_financials_type(self):
        result = get_fundamentals("AAPL", "financials")
        assert "financials" in result
        assert isinstance(result["financials"], list)

    def test_earnings_type(self):
        result = get_fundamentals("AAPL", "earnings")
        assert "earnings" in result

    def test_all_types_default(self):
        result = get_fundamentals("AAPL")
        assert "info" in result
        assert "financials" in result
        # earnings may fail depending on lxml
        assert "earnings" in result or "earnings_error" in result

    def test_invalid_symbol_still_returns(self):
        """Invalid symbol returns result with data (possibly all None values)."""
        result = get_fundamentals("INVALIDXYZ123", "info")
        assert result["symbol"] == "INVALIDXYZ123"
        assert "info" in result or "info_error" in result


class TestGetFundamentalsErrors:
    """Tests for error handling branches with mocked yfinance."""

    @patch(f"{MODULE}.yf.Ticker")
    def test_info_exception(self, mock_ticker):
        mock_instance = MagicMock()
        type(mock_instance).info = PropertyMock(side_effect=Exception("API Error"))
        mock_instance.quarterly_financials = pd.DataFrame()
        mock_instance.earnings_dates = None
        mock_ticker.return_value = mock_instance

        result = get_fundamentals("AAPL", "info")
        assert "info_error" in result
        assert result["info"] == {}

    @patch(f"{MODULE}.yf.Ticker")
    def test_financials_empty(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.quarterly_financials = pd.DataFrame()
        mock_ticker.return_value = mock_instance

        result = get_fundamentals("AAPL", "financials")
        assert result["financials"] == []

    @patch(f"{MODULE}.yf.Ticker")
    def test_financials_exception(self, mock_ticker):
        mock_instance = MagicMock()
        type(mock_instance).quarterly_financials = PropertyMock(side_effect=Exception("API Error"))
        mock_ticker.return_value = mock_instance

        result = get_fundamentals("AAPL", "financials")
        assert "financials_error" in result
        assert result["financials"] == []

    @patch(f"{MODULE}.yf.Ticker")
    def test_earnings_none(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.earnings_dates = None
        mock_ticker.return_value = mock_instance

        result = get_fundamentals("AAPL", "earnings")
        assert result["earnings"] == []

    @patch(f"{MODULE}.yf.Ticker")
    def test_earnings_exception(self, mock_ticker):
        mock_instance = MagicMock()
        type(mock_instance).earnings_dates = PropertyMock(side_effect=Exception("API Error"))
        mock_ticker.return_value = mock_instance

        result = get_fundamentals("AAPL", "earnings")
        assert "earnings_error" in result
        assert result["earnings"] == []

    @patch(f"{MODULE}.yf.Ticker")
    def test_earnings_keyerror(self, mock_ticker):
        mock_instance = MagicMock()
        type(mock_instance).earnings_dates = PropertyMock(side_effect=KeyError("Earnings Date"))
        mock_ticker.return_value = mock_instance

        result = get_fundamentals("AAPL", "earnings")
        assert "earnings_error" in result
        assert "Earnings Date" in result["earnings_error"]

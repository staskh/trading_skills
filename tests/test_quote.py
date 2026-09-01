# ABOUTME: Tests for stock quote module using real Yahoo Finance data.
# ABOUTME: Validates price retrieval, field presence, and error handling.

from datetime import date
from unittest.mock import patch

from trading_skills.quote import get_quote


class TestGetQuote:
    """Tests for get_quote with real Yahoo Finance data."""

    def test_valid_symbol(self):
        result = get_quote("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["price"] is not None
        assert isinstance(result["price"], (int, float))
        assert result["price"] > 0

    def test_expected_fields(self):
        result = get_quote("MSFT")
        expected = [
            "symbol",
            "name",
            "price",
            "volume",
            "market_cap",
            "as_of_session",
            "market_open_now",
        ]
        for field in expected:
            assert field in result, f"Missing field: {field}"

    def test_numeric_fields(self):
        result = get_quote("AAPL")
        assert isinstance(result["volume"], (int, type(None)))
        assert isinstance(result["market_cap"], (int, float, type(None)))

    def test_invalid_symbol(self):
        result = get_quote("INVALIDXYZ123")
        assert "error" in result

    def test_case_insensitive(self):
        result = get_quote("aapl")
        assert result["symbol"] == "AAPL"


class TestAsOfSession:
    """Regression test for the pre-market stale-change bug: a quote fetched before the
    regular session opens must be labeled with the session its price/change actually
    describe, not silently presented as if it were the still-unopened current session."""

    @patch("trading_skills.quote.latest_trading_date")
    @patch("trading_skills.quote.is_trading_now")
    @patch("trading_skills.quote.yf.Ticker")
    def test_premarket_labels_prior_session(
        self, mock_ticker, mock_is_trading_now, mock_latest_date
    ):
        # Simulate the exact repro: 09:12 ET, before the 09:30 open. Yahoo's
        # regularMarketPrice/Change here still describe yesterday's already-completed
        # close-to-close move (Mon $426.91 -> Tue $392.10), not "today".
        mock_ticker.return_value.info = {
            "regularMarketPrice": 392.10,
            "currentPrice": 392.10,
            "regularMarketChange": -34.81,
            "regularMarketChangePercent": -8.15394,
            "shortName": "Dell Technologies Inc.",
            "volume": 1,
            "averageVolume": 1,
            "marketCap": 1,
            "fiftyTwoWeekHigh": 1,
            "fiftyTwoWeekLow": 1,
            "trailingPE": 1,
            "forwardPE": 1,
            "dividendYield": 1,
            "beta": 1,
        }
        mock_is_trading_now.return_value = False
        mock_latest_date.return_value = date(2026, 7, 28)

        result = get_quote("DELL")

        assert result["as_of_session"] == "2026-07-28"
        assert result["market_open_now"] is False

    @patch("trading_skills.quote.latest_trading_date")
    @patch("trading_skills.quote.is_trading_now")
    @patch("trading_skills.quote.yf.Ticker")
    def test_regular_session_labels_today(self, mock_ticker, mock_is_trading_now, mock_latest_date):
        mock_ticker.return_value.info = {
            "regularMarketPrice": 386.47,
            "currentPrice": 386.47,
            "regularMarketChange": -5.62,
            "regularMarketChangePercent": -1.43,
            "shortName": "Dell Technologies Inc.",
            "volume": 1,
            "averageVolume": 1,
            "marketCap": 1,
            "fiftyTwoWeekHigh": 1,
            "fiftyTwoWeekLow": 1,
            "trailingPE": 1,
            "forwardPE": 1,
            "dividendYield": 1,
            "beta": 1,
        }
        mock_is_trading_now.return_value = True
        mock_latest_date.return_value = date(2026, 7, 29)

        result = get_quote("DELL")

        assert result["as_of_session"] == "2026-07-29"
        assert result["market_open_now"] is True

# ABOUTME: Tests for earnings calendar module using real Yahoo Finance data.
# ABOUTME: Validates single and multiple symbol earnings date retrieval.

from unittest.mock import MagicMock, patch

import pandas as pd

from trading_skills.earnings import get_earnings_info, get_multiple_earnings, get_next_earnings_date

MODULE = "trading_skills.earnings"


class TestGetEarningsInfo:
    """Tests for single symbol earnings lookup."""

    def test_valid_symbol(self):
        result = get_earnings_info("AAPL")
        assert result["symbol"] == "AAPL"
        assert "earnings_date" in result
        assert "timing" in result
        assert "eps_estimate" in result

    def test_timing_values(self):
        result = get_earnings_info("AAPL")
        assert result["timing"] in ["BMO", "AMC", None]

    def test_date_format(self):
        result = get_earnings_info("AAPL")
        if result["earnings_date"]:
            date = result["earnings_date"]
            assert len(date) == 10
            assert date[4] == "-" and date[7] == "-"

    def test_eps_estimate_type(self):
        result = get_earnings_info("AAPL")
        eps = result["eps_estimate"]
        assert eps is None or isinstance(eps, (int, float))

    def test_invalid_symbol(self):
        result = get_earnings_info("INVALIDXYZ123")
        assert "error" in result


class TestGetMultipleEarnings:
    """Tests for multiple symbol earnings lookup."""

    def test_multiple_symbols(self):
        result = get_multiple_earnings(["AAPL", "MSFT", "GOOGL"])
        assert "results" in result
        assert len(result["results"]) == 3

    def test_each_result_has_fields(self):
        result = get_multiple_earnings(["AAPL", "MSFT"])
        for r in result["results"]:
            assert "symbol" in r
            assert "earnings_date" in r

    def test_sorted_by_date(self):
        result = get_multiple_earnings(["AAPL", "MSFT", "GOOGL"])
        dates = [r["earnings_date"] or "9999-99-99" for r in result["results"]]
        assert dates == sorted(dates)


class TestGetNextEarningsDate:
    """Tests for get_next_earnings_date shared function."""

    @patch(f"{MODULE}.yf.Ticker")
    def test_returns_date_from_calendar(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.calendar = {"Earnings Date": ["2025-04-15"]}
        mock_ticker.return_value = mock_instance

        result = get_next_earnings_date("AAPL")
        assert result == "2025-04-15"

    @patch(f"{MODULE}.yf.Ticker")
    def test_fallback_to_earnings_dates(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.calendar = None
        future_date = pd.Timestamp("2027-04-15 16:00:00", tz="America/New_York")
        df = pd.DataFrame(
            {"EPS Estimate": [1.5]},
            index=pd.DatetimeIndex([future_date]),
        )
        mock_instance.earnings_dates = df
        mock_ticker.return_value = mock_instance

        result = get_next_earnings_date("AAPL")
        assert result == "2027-04-15"

    @patch(f"{MODULE}.yf.Ticker")
    def test_fallback_to_info_timestamp(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.calendar = None
        mock_instance.earnings_dates = None
        # timestamp for 2025-04-15 12:00:00 UTC
        mock_instance.info = {"earningsTimestamp": 1744718400}
        mock_ticker.return_value = mock_instance

        result = get_next_earnings_date("AAPL")
        assert result is not None
        assert "2025" in result

    @patch(f"{MODULE}.yf.Ticker")
    def test_returns_none_when_no_data(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.calendar = None
        mock_instance.earnings_dates = None
        mock_instance.info = {}
        mock_ticker.return_value = mock_instance

        result = get_next_earnings_date("AAPL")
        assert result is None

    @patch(f"{MODULE}.yf.Ticker")
    def test_exception_returns_none(self, mock_ticker):
        mock_ticker.side_effect = Exception("API Error")
        result = get_next_earnings_date("AAPL")
        assert result is None


class TestGetEarningsInfoEdgeCases:
    """Tests for edge cases with mocked yfinance."""

    @patch(f"{MODULE}.yf.Ticker")
    def test_no_earnings_dates(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {"regularMarketPrice": 150.0}
        mock_instance.earnings_dates = None
        mock_ticker.return_value = mock_instance

        result = get_earnings_info("AAPL")
        assert result["earnings_date"] is None
        assert result["timing"] is None
        assert result["eps_estimate"] is None

    @patch(f"{MODULE}.yf.Ticker")
    def test_empty_earnings_dates(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {"regularMarketPrice": 150.0}
        mock_instance.earnings_dates = pd.DataFrame()
        mock_ticker.return_value = mock_instance

        result = get_earnings_info("AAPL")
        assert result["earnings_date"] is None

    @patch(f"{MODULE}.yf.Ticker")
    def test_past_earnings_only(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {"regularMarketPrice": 150.0}
        # Create earnings dates in the past
        past_dates = pd.DatetimeIndex(
            [
                pd.Timestamp("2024-01-15", tz="America/New_York"),
                pd.Timestamp("2023-10-15", tz="America/New_York"),
            ]
        )
        df = pd.DataFrame(
            {
                "EPS Estimate": [1.5, 1.3],
                "Reported EPS": [1.6, 1.4],
                "Surprise(%)": [6.7, 7.7],
            },
            index=past_dates,
        )
        mock_instance.earnings_dates = df
        mock_ticker.return_value = mock_instance

        result = get_earnings_info("AAPL")
        # Should use most recent past date
        assert result["earnings_date"] == "2024-01-15"

    @patch(f"{MODULE}.yf.Ticker")
    def test_exception_handling(self, mock_ticker):
        mock_ticker.side_effect = Exception("API Error")

        result = get_earnings_info("AAPL")
        assert result["symbol"] == "AAPL"
        assert "error" in result
        assert result["earnings_date"] is None
        assert result["timing"] is None
        assert result["eps_estimate"] is None

    @patch(f"{MODULE}.yf.Ticker")
    def test_no_eps_estimate(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {"regularMarketPrice": 150.0}
        future_date = pd.Timestamp("2027-04-15 16:00:00", tz="America/New_York")
        df = pd.DataFrame(
            {
                "EPS Estimate": [None],
                "Reported EPS": [None],
                "Surprise(%)": [None],
            },
            index=pd.DatetimeIndex([future_date]),
        )
        mock_instance.earnings_dates = df
        mock_ticker.return_value = mock_instance

        result = get_earnings_info("AAPL")
        assert result["eps_estimate"] is None
        assert result["timing"] == "AMC"  # 16:00 = after market close

# ABOUTME: Tests for collar strategy module with mocked Yahoo Finance.
# ABOUTME: Validates volatility, earnings, and collar analysis.

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading_skills.broker.collar import (
    analyze_collar,
    get_earnings_date,
    get_stock_volatility,
)

MODULE = "trading_skills.broker.collar"


class TestGetEarningsDate:
    """Tests for earnings date fetching."""

    @patch(f"{MODULE}.get_next_earnings_date")
    def test_returns_earnings_date(self, mock_ned):
        mock_ned.return_value = "2025-04-15"

        dt, timing = get_earnings_date("AAPL")
        assert dt is not None
        assert dt.month == 4
        assert dt.day == 15

    @patch(f"{MODULE}.get_next_earnings_date")
    def test_no_earnings_date(self, mock_ned):
        mock_ned.return_value = None

        dt, timing = get_earnings_date("AAPL")
        assert dt is None

    @patch(f"{MODULE}.get_next_earnings_date")
    def test_exception_returns_none(self, mock_ned):
        mock_ned.side_effect = Exception("API Error")
        dt, timing = get_earnings_date("AAPL")
        assert dt is None


class TestGetStockVolatility:
    """Tests for volatility calculation."""

    @patch(f"{MODULE}.yf.Ticker")
    def test_returns_volatility(self, mock_ticker):
        dates = pd.date_range(end=datetime.now(), periods=60, freq="D")
        np.random.seed(42)
        prices = 100 + np.cumsum(np.random.randn(60) * 2)
        mock_df = pd.DataFrame(
            {
                "Open": prices - 0.5,
                "High": prices + 1,
                "Low": prices - 1,
                "Close": prices,
                "Volume": np.random.randint(1000000, 5000000, 60),
            },
            index=dates,
        )
        mock_instance = MagicMock()
        mock_instance.history.return_value = mock_df
        mock_ticker.return_value = mock_instance

        result = get_stock_volatility("AAPL")
        assert "annual_vol" in result
        assert "daily_vol" in result
        assert "vol_class" in result
        assert result["annual_vol"] > 0
        assert result["vol_class"] in ["LOW", "MODERATE", "HIGH", "VERY HIGH", "EXTREME"]

    @patch(f"{MODULE}.yf.Ticker")
    def test_insufficient_data(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.history.return_value = pd.DataFrame(
            {"Close": [100, 101]}, index=pd.date_range("2025-01-01", periods=2)
        )
        mock_ticker.return_value = mock_instance

        result = get_stock_volatility("AAPL")
        assert "error" in result

    @patch(f"{MODULE}.yf.Ticker")
    def test_expected_moves(self, mock_ticker):
        dates = pd.date_range(end=datetime.now(), periods=60, freq="D")
        prices = np.linspace(100, 110, 60)
        mock_df = pd.DataFrame(
            {
                "Open": prices,
                "High": prices + 1,
                "Low": prices - 1,
                "Close": prices,
                "Volume": [1000000] * 60,
            },
            index=dates,
        )
        mock_instance = MagicMock()
        mock_instance.history.return_value = mock_df
        mock_ticker.return_value = mock_instance

        result = get_stock_volatility("AAPL")
        assert "move_1_week" in result
        assert "move_2_weeks" in result
        assert "move_3_weeks" in result
        assert result["move_1_week"] < result["move_2_weeks"] < result["move_3_weeks"]


class TestAnalyzeCollar:
    """Tests for collar analysis with mocked data."""

    @patch(f"{MODULE}.get_call_market_price")
    @patch(f"{MODULE}.get_put_chain")
    @patch("trading_skills.options.get_expiries")
    @patch(f"{MODULE}.get_stock_volatility")
    def test_basic_analysis(self, mock_vol, mock_expiries, mock_puts, mock_call_price):
        mock_vol.return_value = {
            "annual_vol": 0.35,
            "daily_vol": 0.022,
            "vol_class": "MODERATE",
            "current_price": 150.0,
            "move_1_week": 5.0,
            "move_1_week_pct": 3.3,
            "move_2_weeks": 7.0,
            "move_2_weeks_pct": 4.7,
            "move_3_weeks": 8.5,
            "move_3_weeks_pct": 5.7,
        }

        future = datetime.now() + timedelta(days=30)
        expiry = future.strftime("%Y-%m-%d")
        mock_expiries.return_value = [expiry]

        mock_puts.return_value = [
            {"strike": 135.0, "bid": 1.50, "ask": 2.00, "mid": 1.75, "oi": 100, "iv": 0.40},
            {"strike": 140.0, "bid": 2.50, "ask": 3.00, "mid": 2.75, "oi": 200, "iv": 0.38},
            {"strike": 143.0, "bid": 3.50, "ask": 4.00, "mid": 3.75, "oi": 150, "iv": 0.36},
        ]

        mock_call_price.return_value = 25.0

        earnings_date = datetime.now() + timedelta(days=20)
        result = analyze_collar(
            symbol="AAPL",
            current_price=150.0,
            long_strike=130.0,
            long_expiry="20260121",
            long_qty=5,
            long_cost=25.0,
            short_positions=[{"strike": 160.0, "expiry": "20250321"}],
            earnings_date=earnings_date,
        )

        assert "volatility" in result
        assert "put_analysis" in result
        assert "symbol" in result
        assert result["symbol"] == "AAPL"

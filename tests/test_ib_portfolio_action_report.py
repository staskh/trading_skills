# ABOUTME: Tests for IB portfolio action report module with mocked dependencies.
# ABOUTME: Validates spread grouping, recommendations, and analysis functions.

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading_skills.broker.portfolio_action import (
    calculate_otm_pct,
    fetch_earnings_date,
    fetch_technicals,
    get_spread_recommendation,
    group_positions_into_spreads,
)
from trading_skills.utils import days_to_expiry

MODULE = "trading_skills.broker.portfolio_action"


class TestCalculateDaysToExpiry:
    """Tests for days to expiry calculation."""

    def test_valid_expiry(self):
        future = datetime.now() + timedelta(days=10)
        expiry_str = future.strftime("%Y%m%d")
        days = days_to_expiry(expiry_str)
        assert 9 <= days <= 11

    def test_invalid_expiry(self):
        assert days_to_expiry("invalid") == 999

    def test_empty_expiry(self):
        assert days_to_expiry("") == 999


class TestCalculateOtmPct:
    """Tests for OTM percentage calculation."""

    def test_call_otm(self):
        assert calculate_otm_pct(110, 100, "C") == 10.0

    def test_call_itm(self):
        assert calculate_otm_pct(90, 100, "C") == -10.0

    def test_put_otm(self):
        assert calculate_otm_pct(90, 100, "P") == 10.0

    def test_put_itm(self):
        assert calculate_otm_pct(110, 100, "P") == -10.0

    def test_zero_underlying_returns_zero(self):
        assert calculate_otm_pct(100, 0, "C") == 0

    def test_zero_strike_returns_zero(self):
        assert calculate_otm_pct(0, 100, "C") == 0


class TestGetSpreadRecommendation:
    """Tests for spread recommendation calculation."""

    def test_short_itm_expiring_soon_is_red(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 2, "quantity": -10},
            "long": None,
            "underlying_price": 105,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert level == "red"
        assert emoji == "🔴"

    def test_short_otm_expiring_soon_is_green(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 2, "quantity": -10},
            "long": None,
            "underlying_price": 80,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert level == "green"
        assert emoji == "🟢"

    def test_earnings_before_expiration_is_red(self):
        today = datetime.now()
        earnings_date = (today + timedelta(days=3)).strftime("%Y-%m-%d")
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 5, "quantity": -10},
            "long": None,
            "underlying_price": 90,
        }
        emoji, level, reason = get_spread_recommendation(spread, earnings_date, today)
        assert level == "red"
        assert "Earnings" in reason or "EARNINGS" in reason

    def test_short_itm_week_out_is_red(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 5, "quantity": -10},
            "long": None,
            "underlying_price": 105,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert level == "red"
        assert "ITM" in reason

    def test_short_otm_week_out_is_yellow(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 5, "quantity": -10},
            "long": None,
            "underlying_price": 90,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert level == "yellow"

    def test_long_only_position_green(self):
        spread = {
            "symbol": "AAPL",
            "short": None,
            "long": {"strike": 100, "days_to_exp": 30, "quantity": 10},
            "underlying_price": 100,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert level == "green"

    def test_long_far_otm_is_yellow(self):
        spread = {
            "symbol": "AAPL",
            "short": None,
            "long": {"strike": 150, "days_to_exp": 30, "quantity": 10},
            "underlying_price": 100,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert level == "yellow"
        assert "OTM" in reason

    def test_vertical_spread_bull_call(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 110, "days_to_exp": 30, "expiry": "20250321", "quantity": -10},
            "long": {"strike": 100, "days_to_exp": 30, "expiry": "20250321", "quantity": 10},
            "underlying_price": 105,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert "Bull call spread" in reason

    def test_diagonal_spread_detection(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 110, "days_to_exp": 14, "expiry": "20250221", "quantity": -10},
            "long": {"strike": 100, "days_to_exp": 60, "expiry": "20250421", "quantity": 10},
            "underlying_price": 105,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert "Diagonal" in reason


class TestGroupPositionsIntoSpreads:
    """Tests for spread grouping logic."""

    def test_single_short_position(self):
        positions = [
            {"symbol": "AAPL", "quantity": -1, "strike": 100, "expiry": "20250321", "right": "C"}
        ]
        spreads = group_positions_into_spreads(positions, "AAPL")
        assert len(spreads) == 1
        assert spreads[0]["short"] is not None
        assert spreads[0]["long"] is None

    def test_single_long_position(self):
        positions = [
            {"symbol": "AAPL", "quantity": 1, "strike": 100, "expiry": "20250321", "right": "C"}
        ]
        spreads = group_positions_into_spreads(positions, "AAPL")
        assert len(spreads) == 1
        assert spreads[0]["long"] is not None
        assert spreads[0]["short"] is None

    def test_matched_vertical_spread(self):
        positions = [
            {"symbol": "AAPL", "quantity": 1, "strike": 100, "expiry": "20250321", "right": "C"},
            {"symbol": "AAPL", "quantity": -1, "strike": 110, "expiry": "20250321", "right": "C"},
        ]
        spreads = group_positions_into_spreads(positions, "AAPL")
        assert len(spreads) == 1
        assert spreads[0]["long"] is not None
        assert spreads[0]["short"] is not None

    def test_unmatched_positions(self):
        positions = [
            {"symbol": "AAPL", "quantity": 2, "strike": 100, "expiry": "20250321", "right": "C"},
            {"symbol": "AAPL", "quantity": -1, "strike": 110, "expiry": "20250321", "right": "C"},
        ]
        spreads = group_positions_into_spreads(positions, "AAPL")
        assert len(spreads) == 2


class TestFetchEarningsDate:
    """Tests for earnings date fetching."""

    @patch(f"{MODULE}.get_next_earnings_date")
    def test_successful_fetch_via_calendar(self, mock_ned):
        mock_ned.return_value = "2025-02-15"

        result = fetch_earnings_date("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["earnings_date"] == "2025-02-15"

    @patch(f"{MODULE}.get_next_earnings_date")
    def test_no_earnings_data(self, mock_ned):
        mock_ned.return_value = None

        result = fetch_earnings_date("INVALID")
        assert result["symbol"] == "INVALID"
        assert result["earnings_date"] is None


class TestFetchTechnicals:
    """Tests for technical analysis fetching."""

    @patch(f"{MODULE}.yf.Ticker")
    def test_returns_indicators(self, mock_ticker):
        dates = pd.date_range(end=datetime.now(), periods=100, freq="D")
        np.random.seed(42)
        mock_df = pd.DataFrame(
            {
                "Open": np.linspace(100, 110, 100) + np.random.randn(100) * 2,
                "High": np.linspace(102, 112, 100) + np.random.randn(100) * 2,
                "Low": np.linspace(98, 108, 100) + np.random.randn(100) * 2,
                "Close": np.linspace(100, 110, 100),
                "Volume": np.random.randint(1000000, 5000000, 100),
            },
            index=dates,
        )
        mock_instance = MagicMock()
        mock_instance.history.return_value = mock_df
        mock_ticker.return_value = mock_instance

        result = fetch_technicals("AAPL")
        assert result["symbol"] == "AAPL"
        assert "rsi" in result
        assert "trend" in result

    @patch(f"{MODULE}.yf.Ticker")
    def test_empty_data(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.history.return_value = pd.DataFrame()
        mock_ticker.return_value = mock_instance

        result = fetch_technicals("INVALID")
        assert "error" in result

    @patch(f"{MODULE}.yf.Ticker")
    def test_exception_handling(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.history.side_effect = Exception("API Error")
        mock_ticker.return_value = mock_instance

        result = fetch_technicals("AAPL")
        assert "error" in result

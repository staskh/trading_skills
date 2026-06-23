# ABOUTME: Tests for IB portfolio action report module with mocked dependencies.
# ABOUTME: Validates spread grouping, recommendations, and analysis functions.

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading_skills.broker.portfolio_action import (
    analyze_portfolio,
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

    @patch(f"{MODULE}.get_earnings_info")
    def test_successful_fetch_returns_date_and_timing(self, mock_gei):
        mock_gei.return_value = {
            "symbol": "AAPL",
            "earnings_date": "2025-02-15",
            "timing": "AMC",
        }

        result = fetch_earnings_date("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["earnings_date"] == "2025-02-15"
        assert result["earnings_timing"] == "AMC"

    @patch(f"{MODULE}.get_earnings_info")
    def test_bmo_timing_returned(self, mock_gei):
        mock_gei.return_value = {
            "symbol": "WMT",
            "earnings_date": "2025-05-21",
            "timing": "BMO",
        }

        result = fetch_earnings_date("WMT")
        assert result["earnings_timing"] == "BMO"

    @patch(f"{MODULE}.get_earnings_info")
    def test_no_earnings_data(self, mock_gei):
        mock_gei.return_value = {"symbol": "INVALID", "earnings_date": None, "timing": None}

        result = fetch_earnings_date("INVALID")
        assert result["symbol"] == "INVALID"
        assert result["earnings_date"] is None
        assert result["earnings_timing"] is None

    @patch(f"{MODULE}.get_earnings_info")
    def test_unknown_timing_is_none(self, mock_gei):
        mock_gei.return_value = {
            "symbol": "XOM",
            "earnings_date": "2025-07-31",
            "timing": None,
        }

        result = fetch_earnings_date("XOM")
        assert result["earnings_timing"] is None


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

    @patch(f"{MODULE}.yf.Ticker")
    def test_bearish_trend(self, mock_ticker):
        dates = pd.date_range(end=datetime.now(), periods=100, freq="D")
        # Declining prices produce bearish signals
        prices = np.linspace(110, 100, 100)
        mock_df = pd.DataFrame(
            {
                "Open": prices + 0.5,
                "High": prices + 1,
                "Low": prices - 1,
                "Close": prices,
                "Volume": np.random.randint(1000000, 5000000, 100),
            },
            index=dates,
        )
        mock_instance = MagicMock()
        mock_instance.history.return_value = mock_df
        mock_ticker.return_value = mock_instance

        result = fetch_technicals("AAPL")
        assert result["symbol"] == "AAPL"
        assert result.get("trend") in ["bearish", "neutral", "bullish"]


class TestGetSpreadRecommendationEdgeCases:
    """Additional edge case tests for spread recommendations."""

    def test_short_itm_8_to_14_days_is_yellow(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 10, "quantity": -5},
            "long": None,
            "underlying_price": 105,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert level in ("red", "yellow")
        assert "ITM" in reason

    def test_earnings_yellow_not_critical(self):
        today = datetime.now()
        # Earnings in 5 days, expiry in 20 days — not critical (>3 days before expiry)
        earnings_date = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 20, "quantity": -5},
            "long": None,
            "underlying_price": 90,
        }
        emoji, level, reason = get_spread_recommendation(spread, earnings_date, today)
        assert level in ("yellow", "red")
        assert "arnings" in reason

    def test_bear_call_spread_detected(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 30, "expiry": "20250321", "quantity": -10},
            "long": {"strike": 110, "days_to_exp": 30, "expiry": "20250321", "quantity": 10},
            "underlying_price": 105,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert "Bear call spread" in reason

    def test_futures_position_detected(self):
        spread = {
            "symbol": "ES",
            "short": {"strike": 0, "days_to_exp": 30, "expiry": "20250321", "quantity": -1},
            "long": {"strike": 0, "days_to_exp": 30, "expiry": "20250321", "quantity": 1},
            "underlying_price": 5000,
        }
        emoji, level, reason = get_spread_recommendation(spread, None, datetime.now())
        assert "Futures" in reason

    def test_invalid_earnings_date_no_crash(self):
        spread = {
            "symbol": "AAPL",
            "short": {"strike": 100, "days_to_exp": 20, "quantity": -5},
            "long": None,
            "underlying_price": 90,
        }
        # Should not crash with a badly formatted date
        emoji, level, reason = get_spread_recommendation(spread, "not-a-date", datetime.now())
        assert level in ("green", "yellow", "red")


class TestAnalyzePortfolio:
    """Tests for the analyze_portfolio pure analytics function."""

    def _make_position(self, symbol, quantity, strike, expiry, right="C", avg_cost=5.0):
        return {
            "symbol": symbol,
            "sec_type": "OPT",
            "quantity": quantity,
            "strike": strike,
            "expiry": expiry,
            "right": right,
            "avg_cost": avg_cost,
        }

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_basic_structure(self, mock_earnings, mock_technicals):
        mock_earnings.return_value = {"symbol": "AAPL", "earnings_date": "2026-09-01"}
        mock_technicals.return_value = {"symbol": "AAPL", "trend": "bullish"}

        future_expiry = (datetime.now() + timedelta(days=60)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123"],
            "positions": {
                "U123": [
                    self._make_position("AAPL", 1, 150.0, future_expiry),
                    self._make_position("AAPL", -1, 160.0, future_expiry),
                ]
            },
            "prices": {"AAPL": 155.0},
        }

        result = analyze_portfolio(data)
        assert "generated_at" in result
        assert "summary" in result
        assert "spreads" in result
        assert "accounts" in result
        assert result["accounts"] == ["U123"]

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_urgency_categories(self, mock_earnings, mock_technicals):
        mock_earnings.return_value = {"symbol": "NVDA", "earnings_date": None}
        mock_technicals.return_value = {"symbol": "NVDA", "trend": "neutral"}

        today = datetime.now()
        exp_1d = (today + timedelta(days=1)).strftime("%Y%m%d")
        exp_5d = (today + timedelta(days=5)).strftime("%Y%m%d")
        exp_15d = (today + timedelta(days=15)).strftime("%Y%m%d")
        exp_60d = (today + timedelta(days=60)).strftime("%Y%m%d")

        data = {
            "accounts": ["U456"],
            "positions": {
                "U456": [
                    # 4 naked shorts at different DTE ranges
                    self._make_position("NVDA", -1, 200.0, exp_1d),
                    self._make_position("NVDA", -1, 210.0, exp_5d),
                    self._make_position("NVDA", -1, 215.0, exp_15d),
                    self._make_position("NVDA", -1, 220.0, exp_60d),
                ]
            },
            "prices": {"NVDA": 195.0},
        }

        result = analyze_portfolio(data)
        urgencies = {s["urgency"] for s in result["spreads"]}
        assert "expiring_2_days" in urgencies
        assert "expiring_1_week" in urgencies
        assert "expiring_2_weeks" in urgencies
        assert "longer_dated" in urgencies

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_earnings_calendar_populated(self, mock_earnings, mock_technicals):
        mock_earnings.return_value = {"symbol": "AAPL", "earnings_date": "2026-06-15"}
        mock_technicals.return_value = {"symbol": "AAPL", "trend": "neutral"}

        future_expiry = (datetime.now() + timedelta(days=90)).strftime("%Y%m%d")
        data = {
            "accounts": ["U789"],
            "positions": {
                "U789": [
                    self._make_position("AAPL", 1, 150.0, future_expiry),
                ]
            },
            "prices": {"AAPL": 155.0},
        }

        result = analyze_portfolio(data)
        assert "earnings_calendar" in result
        assert "account_summary" in result
        assert len(result["account_summary"]) == 1
        assert result["account_summary"][0]["account"] == "U789"

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_empty_positions(self, mock_earnings, mock_technicals):
        mock_earnings.return_value = {"symbol": "X", "earnings_date": None}
        mock_technicals.return_value = {"symbol": "X", "trend": "neutral"}

        data = {
            "accounts": ["U000"],
            "positions": {"U000": []},
            "prices": {},
        }

        result = analyze_portfolio(data)
        assert result["summary"]["red_count"] == 0
        assert result["summary"]["green_count"] == 0
        assert result["spreads"] == []

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_earnings_this_week(self, mock_earnings, mock_technicals):
        today = datetime.now()
        earnings_date = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        mock_earnings.return_value = {"symbol": "MSFT", "earnings_date": earnings_date}
        mock_technicals.return_value = {"symbol": "MSFT", "trend": "bullish"}

        future_expiry = (today + timedelta(days=30)).strftime("%Y%m%d")
        data = {
            "accounts": ["U111"],
            "positions": {
                "U111": [
                    self._make_position("MSFT", 1, 350.0, future_expiry),
                ]
            },
            "prices": {"MSFT": 360.0},
        }

        result = analyze_portfolio(data)
        earnings_urgency_spreads = [
            s for s in result["spreads"] if s.get("earnings_urgency") == "this_week"
        ]
        assert len(earnings_urgency_spreads) > 0

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_earnings_timing_in_output(self, mock_earnings, mock_technicals):
        mock_earnings.return_value = {
            "symbol": "AAPL",
            "earnings_date": "2026-09-01",
            "earnings_timing": "AMC",
        }
        mock_technicals.return_value = {"symbol": "AAPL", "trend": "bullish"}

        future_expiry = (datetime.now() + timedelta(days=60)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123"],
            "positions": {"U123": [self._make_position("AAPL", 1, 150.0, future_expiry)]},
            "prices": {"AAPL": 155.0},
        }

        result = analyze_portfolio(data)
        assert "earnings_timing" in result
        assert result["earnings_timing"].get("AAPL") == "AMC"

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_earnings_timing_on_spreads(self, mock_earnings, mock_technicals):
        mock_earnings.return_value = {
            "symbol": "AAPL",
            "earnings_date": "2026-09-01",
            "earnings_timing": "BMO",
        }
        mock_technicals.return_value = {"symbol": "AAPL", "trend": "bullish"}

        future_expiry = (datetime.now() + timedelta(days=60)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123"],
            "positions": {"U123": [self._make_position("AAPL", 1, 150.0, future_expiry)]},
            "prices": {"AAPL": 155.0},
        }

        result = analyze_portfolio(data)
        spread = result["spreads"][0]
        assert spread.get("earnings_timing") == "BMO"

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_earnings_calendar_has_timing(self, mock_earnings, mock_technicals):
        mock_earnings.return_value = {
            "symbol": "AAPL",
            "earnings_date": "2026-09-01",
            "earnings_timing": "AMC",
        }
        mock_technicals.return_value = {"symbol": "AAPL", "trend": "bullish"}

        future_expiry = (datetime.now() + timedelta(days=60)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123"],
            "positions": {"U123": [self._make_position("AAPL", 1, 150.0, future_expiry)]},
            "prices": {"AAPL": 155.0},
        }

        result = analyze_portfolio(data)
        assert len(result["earnings_calendar"]) > 0
        cal_entry = result["earnings_calendar"][0]
        assert "timing" in cal_entry
        assert cal_entry["timing"] == "AMC"

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_today_bmo_earnings_status_after_open(self, mock_earnings, mock_technicals):
        """BMO earnings on today's date should be 'reported' after market open."""
        from zoneinfo import ZoneInfo

        _NY = ZoneInfo("America/New_York")
        today_str = datetime.now(_NY).strftime("%Y-%m-%d")

        mock_earnings.return_value = {
            "symbol": "WMT",
            "earnings_date": today_str,
            "earnings_timing": "BMO",
        }
        mock_technicals.return_value = {"symbol": "WMT", "trend": "bearish"}

        future_expiry = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123"],
            "positions": {"U123": [self._make_position("WMT", 1, 100.0, future_expiry)]},
            "prices": {"WMT": 121.0},
        }

        # Simulate time after market open (10:00 ET)
        fake_now = datetime.now(_NY).replace(hour=10, minute=0)
        with patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            result = analyze_portfolio(data)

        cal_entry = next((e for e in result["earnings_calendar"] if e["symbol"] == "WMT"), None)
        assert cal_entry is not None
        assert cal_entry.get("status") == "reported"

    @patch(f"{MODULE}.fetch_technicals")
    @patch(f"{MODULE}.fetch_earnings_date")
    def test_today_amc_earnings_status_before_close(self, mock_earnings, mock_technicals):
        """AMC earnings on today's date should be 'pending' before market close."""
        from zoneinfo import ZoneInfo

        _NY = ZoneInfo("America/New_York")
        today_str = datetime.now(_NY).strftime("%Y-%m-%d")

        mock_earnings.return_value = {
            "symbol": "NVDA",
            "earnings_date": today_str,
            "earnings_timing": "AMC",
        }
        mock_technicals.return_value = {"symbol": "NVDA", "trend": "bullish"}

        future_expiry = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123"],
            "positions": {"U123": [self._make_position("NVDA", 1, 200.0, future_expiry)]},
            "prices": {"NVDA": 221.0},
        }

        # Simulate time before market close (13:00 ET)
        fake_now = datetime.now(_NY).replace(hour=13, minute=0)
        with patch(f"{MODULE}.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.strptime = datetime.strptime
            result = analyze_portfolio(data)

        cal_entry = next((e for e in result["earnings_calendar"] if e["symbol"] == "NVDA"), None)
        assert cal_entry is not None
        assert cal_entry.get("status") == "pending"


# ---------------------------------------------------------------------------
# data_delay reflects market session (issue #68)
# ---------------------------------------------------------------------------


def _minimal_data():
    future_expiry = (datetime.now() + timedelta(days=60)).strftime("%Y%m%d")
    return {
        "accounts": ["U123"],
        "positions": {
            "U123": [
                {
                    "symbol": "AAPL",
                    "sec_type": "OPT",
                    "quantity": 1,
                    "strike": 150.0,
                    "expiry": future_expiry,
                    "right": "C",
                    "avg_cost": 5.0,
                },
                {
                    "symbol": "AAPL",
                    "sec_type": "OPT",
                    "quantity": -1,
                    "strike": 160.0,
                    "expiry": future_expiry,
                    "right": "C",
                    "avg_cost": 2.0,
                },
            ]
        },
        "prices": {"AAPL": 155.0},
    }


@patch(f"{MODULE}.fetch_technicals")
@patch(f"{MODULE}.fetch_earnings_date")
@patch(f"{MODULE}.is_trading_now", return_value=True)
def test_data_delay_real_time_during_market_hours(mock_live, mock_earnings, mock_tech):
    mock_earnings.return_value = {"symbol": "AAPL", "earnings_date": None}
    mock_tech.return_value = {"symbol": "AAPL", "trend": "neutral"}
    result = analyze_portfolio(_minimal_data())
    assert result["data_delay"] == "real-time"


@patch(f"{MODULE}.fetch_technicals")
@patch(f"{MODULE}.fetch_earnings_date")
@patch(f"{MODULE}.is_trading_now", return_value=False)
def test_data_delay_extended_hours_outside_market(mock_live, mock_earnings, mock_tech):
    mock_earnings.return_value = {"symbol": "AAPL", "earnings_date": None}
    mock_tech.return_value = {"symbol": "AAPL", "trend": "neutral"}
    result = analyze_portfolio(_minimal_data())
    assert result["data_delay"] == "extended-hours"

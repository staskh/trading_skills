# ABOUTME: Tests for collar strategy module with mocked Yahoo Finance.
# ABOUTME: Validates volatility, earnings, collar analysis, and reports.

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading_skills.broker.collar import (
    analyze_collar,
    generate_markdown_report,
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


class TestGenerateMarkdownReport:
    """Tests for markdown report generation."""

    def _make_analysis(self, vol_class="MODERATE", with_earnings=True, with_puts=True):
        today = datetime.now()
        earnings = today + timedelta(days=20) if with_earnings else None
        days_to_earnings = 20 if with_earnings else None

        put_analysis = []
        if with_puts:
            put_analysis = [
                {
                    "expiry": (today + timedelta(days=30)).strftime("%Y-%m-%d"),
                    "days_out": 30,
                    "days_after_earnings": 10 if with_earnings else None,
                    "strike": 140.0,
                    "otm_pct": 6.7,
                    "cost_per_contract": 2.50,
                    "total_cost": 1250.0,
                    "scenarios": {
                        "gap_up_10": {"price": 165.0, "put_value": 50.0, "put_pnl": -1200.0},
                        "flat": {"price": 150.0, "put_value": 200.0, "put_pnl": -1050.0},
                        "gap_down_10": {"price": 135.0, "put_value": 2500.0, "put_pnl": 1250.0},
                        "gap_down_15": {"price": 127.5, "put_value": 6250.0, "put_pnl": 5000.0},
                    },
                }
            ]

        return {
            "symbol": "AAPL",
            "current_price": 150.0,
            "long_strike": 130.0,
            "long_expiry": "20260121",
            "long_qty": 5,
            "long_cost": 25.0,
            "long_value_now": 30.0,
            "short_positions": [{"strike": 160.0, "expiry": "20250321", "qty": -5}],
            "is_proper_pmcc": True,
            "short_above_long": True,
            "earnings_date": earnings,
            "days_to_earnings": days_to_earnings,
            "put_analysis": put_analysis,
            "unprotected_loss_10": 5000.0,
            "unprotected_loss_15": 8000.0,
            "unprotected_gain_10": 4000.0,
            "volatility": {
                "annual_vol": 0.35,
                "annual_vol_pct": 35.0,
                "daily_vol": 0.022,
                "vol_class": vol_class,
                "current_price": 150.0,
                "move_1_week": 5.0,
                "move_1_week_pct": 3.3,
                "move_2_weeks": 7.0,
                "move_2_weeks_pct": 4.7,
                "move_3_weeks": 8.5,
                "move_3_weeks_pct": 5.7,
            },
        }

    def test_basic_report(self):
        analysis = self._make_analysis()
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "AAPL Tactical Collar Strategy Report" in content
            assert "Position Summary" in content
            assert "PMCC Health Check" in content
            assert "Earnings Risk Assessment" in content
            assert "Put Protection Analysis" in content

    def test_report_with_earnings_critical(self):
        analysis = self._make_analysis()
        analysis["days_to_earnings"] = 5
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "CRITICAL" in content

    def test_report_without_earnings(self):
        analysis = self._make_analysis(with_earnings=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "No upcoming earnings date found" in content

    def test_report_no_puts(self):
        analysis = self._make_analysis(with_puts=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "No suitable put options found" in content

    def test_extreme_volatility_timing(self):
        analysis = self._make_analysis(vol_class="EXTREME")
        analysis["volatility"]["vol_class"] = "EXTREME"
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "BUY DAY BEFORE EARNINGS" in content
            assert "Day-Before Strike Selection" in content

    def test_high_volatility_timing(self):
        analysis = self._make_analysis(vol_class="HIGH")
        analysis["volatility"]["vol_class"] = "HIGH"
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "BUY 3-5 DAYS BEFORE" in content

    def test_low_volatility_timing(self):
        analysis = self._make_analysis(vol_class="LOW")
        analysis["volatility"]["vol_class"] = "LOW"
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "BUY 1-2 WEEKS BEFORE" in content

    def test_broken_pmcc_warning(self):
        analysis = self._make_analysis()
        analysis["is_proper_pmcc"] = False
        analysis["short_above_long"] = False
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "collar.md"
            generate_markdown_report(analysis, output)
            content = output.read_text()
            assert "BROKEN PMCC" in content

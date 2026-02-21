# ABOUTME: Tests for IB portfolio action report module with mocked dependencies.
# ABOUTME: Validates spread grouping, recommendations, report generation, and PDF output.

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading_skills.broker.portfolio_action import (
    calculate_days_to_expiry,
    calculate_otm_pct,
    convert_to_pdf,
    fetch_earnings_date,
    fetch_technicals,
    format_expiry,
    generate_report,
    get_spread_recommendation,
    group_positions_into_spreads,
)

MODULE = "trading_skills.broker.portfolio_action"


class TestCalculateDaysToExpiry:
    """Tests for days to expiry calculation."""

    def test_valid_expiry(self):
        future = datetime.now() + timedelta(days=10)
        expiry_str = future.strftime("%Y%m%d")
        days = calculate_days_to_expiry(expiry_str)
        assert 9 <= days <= 11

    def test_invalid_expiry(self):
        assert calculate_days_to_expiry("invalid") == 999

    def test_empty_expiry(self):
        assert calculate_days_to_expiry("") == 999


class TestFormatExpiry:
    """Tests for expiry date formatting."""

    def test_valid_expiry_format(self):
        assert format_expiry("20250321") == "Mar 21"

    def test_invalid_expiry_returns_original(self):
        assert format_expiry("invalid") == "invalid"

    def test_empty_expiry_returns_dash(self):
        assert format_expiry("") == "-"

    def test_none_expiry_returns_dash(self):
        assert format_expiry(None) == "-"


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


class TestGenerateReport:
    """Tests for report generation."""

    def test_report_contains_technicals(self):
        today = datetime.now()
        expiry = (today + timedelta(days=30)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123456"],
            "positions": {
                "U123456": [
                    {
                        "symbol": "AAPL",
                        "sec_type": "OPT",
                        "quantity": -1,
                        "avg_cost": 2.50,
                        "strike": 180,
                        "expiry": expiry,
                        "right": "C",
                    }
                ]
            },
            "prices": {"AAPL": 175.0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.md"
            with (
                patch(f"{MODULE}.fetch_earnings_date") as mock_earnings,
                patch(f"{MODULE}.fetch_technicals") as mock_technicals,
            ):
                mock_earnings.return_value = {"symbol": "AAPL", "earnings_date": None}
                mock_technicals.return_value = {
                    "symbol": "AAPL",
                    "rsi": 55.5,
                    "trend": "bullish",
                    "sma20": 172.0,
                    "above_sma20": True,
                }
                content = generate_report(data, output_path)
                assert "TECHNICAL ANALYSIS" in content
                assert "AAPL" in content

    def test_empty_portfolio(self):
        data = {"accounts": ["U123456"], "positions": {"U123456": []}, "prices": {}}
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.md"
            content = generate_report(data, output_path)
            assert "IB Portfolio Action Report" in content

    def test_multiple_accounts(self):
        today = datetime.now()
        expiry = (today + timedelta(days=30)).strftime("%Y%m%d")
        data = {
            "accounts": ["U123456", "U789012"],
            "positions": {
                "U123456": [
                    {
                        "symbol": "AAPL",
                        "sec_type": "OPT",
                        "quantity": -1,
                        "avg_cost": 2.50,
                        "strike": 180,
                        "expiry": expiry,
                        "right": "C",
                    }
                ],
                "U789012": [
                    {
                        "symbol": "GOOG",
                        "sec_type": "OPT",
                        "quantity": -1,
                        "avg_cost": 5.00,
                        "strike": 150,
                        "expiry": expiry,
                        "right": "C",
                    }
                ],
            },
            "prices": {"AAPL": 175.0, "GOOG": 140.0},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.md"
            with (
                patch(f"{MODULE}.fetch_earnings_date") as mock_earnings,
                patch(f"{MODULE}.fetch_technicals") as mock_technicals,
            ):
                mock_earnings.return_value = {"symbol": "TEST", "earnings_date": None}
                mock_technicals.return_value = {"symbol": "TEST", "error": "test"}
                content = generate_report(data, output_path)
                assert "U123456" in content
                assert "U789012" in content


class TestConvertToPdf:
    """Tests for PDF conversion."""

    def test_convert_success(self):
        md_content = "# Test\n\n| Col1 | Col2 |\n|------|------|\n| A | B |\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "test.md"
            pdf_path = Path(tmpdir) / "test.pdf"
            md_path.write_text(md_content)
            result = convert_to_pdf(md_path, pdf_path)
            assert result is True
            assert pdf_path.exists()

    def test_convert_with_emojis(self):
        md_content = "# Test\n🔴 Red 🟡 Yellow 🟢 Green\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            md_path = Path(tmpdir) / "test.md"
            pdf_path = Path(tmpdir) / "test.pdf"
            md_path.write_text(md_content)
            result = convert_to_pdf(md_path, pdf_path)
            assert result is True

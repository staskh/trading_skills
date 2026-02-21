# ABOUTME: Tests for roll analysis module pure logic functions.
# ABOUTME: Validates candidate evaluation, roll calculation, formatting, and report generation.

from datetime import datetime, timedelta

from trading_skills.broker.roll import (
    calculate_roll_options,
    evaluate_short_candidates,
    format_expiry,
    generate_new_short_report,
    generate_report,
    generate_spread_short_report,
)
from trading_skills.utils import days_to_expiry


class TestFormatExpiry:
    """Tests for expiry date formatting."""

    def test_valid_format(self):
        assert format_expiry("20250321") == "Mar 21, 2025"

    def test_invalid_returns_original(self):
        assert format_expiry("invalid") == "invalid"


class TestDaysToExpiry:
    """Tests for days to expiry calculation."""

    def test_future_date(self):
        future = datetime.now() + timedelta(days=30)
        expiry_str = future.strftime("%Y%m%d")
        days = days_to_expiry(expiry_str)
        assert 29 <= days <= 31

    def test_past_date(self):
        past = datetime.now() - timedelta(days=10)
        expiry_str = past.strftime("%Y%m%d")
        days = days_to_expiry(expiry_str)
        assert days < 0

    def test_invalid_returns_999(self):
        assert days_to_expiry("invalid") == 999


class TestEvaluateShortCandidates:
    """Tests for short option candidate evaluation."""

    def test_filters_zero_bid(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 0, "ask": 1.0, "mid": 0.5, "last": 0}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 0

    def test_filters_itm(self):
        quotes = [
            {"strike": 90, "expiry": "20250321", "bid": 12.0, "ask": 13.0, "mid": 12.5, "last": 12}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 0

    def test_otm_call_included(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 1
        assert result[0]["strike"] == 110
        assert result[0]["otm_pct"] == 10.0

    def test_otm_put_included(self):
        quotes = [
            {"strike": 90, "expiry": "20250321", "bid": 1.5, "ask": 2.0, "mid": 1.75, "last": 1.5}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "P", 30)
        assert len(result) == 1
        assert result[0]["otm_pct"] == 10.0

    def test_sorted_by_score_descending(self):
        quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 3.0, "ask": 3.5, "mid": 3.25, "last": 3},
            {"strike": 115, "expiry": "20250321", "bid": 0.5, "ask": 1.0, "mid": 0.75, "last": 0.5},
            {"strike": 110, "expiry": "20250321", "bid": 1.5, "ask": 2.0, "mid": 1.75, "last": 1.5},
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 3
        # Scores should be descending
        for i in range(len(result) - 1):
            assert result[i]["score"] >= result[i + 1]["score"]

    def test_annual_return_calculated(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        # annual_return = (2.0 / 100.0) * (365/30) * 100 = 24.33%
        assert result[0]["annual_return"] > 20

    def test_time_score_preferred_range(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result_30 = evaluate_short_candidates(quotes, 100.0, "C", 30)
        result_7 = evaluate_short_candidates(quotes, 100.0, "C", 7)
        # 30 DTE in preferred 21-60 range, 7 DTE is not
        assert result_30[0]["score"] > result_7[0]["score"]


class TestCalculateRollOptions:
    """Tests for roll credit/debit calculation."""

    def test_credit_roll(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 3.0, "ask": 3.5, "mid": 3.25, "last": 3}
        ]
        buy_price = 1.50
        result = calculate_roll_options(current, target_quotes, buy_price)
        assert len(result) == 1
        assert result[0]["net"] == 1.50  # 3.0 - 1.5
        assert result[0]["net_type"] == "credit"

    def test_debit_roll(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 0.50, "ask": 1.0, "mid": 0.75, "last": 0.5}
        ]
        buy_price = 2.00
        result = calculate_roll_options(current, target_quotes, buy_price)
        assert len(result) == 1
        assert result[0]["net"] == -1.50  # 0.5 - 2.0
        assert result[0]["net_type"] == "debit"

    def test_filters_zero_bid(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 0, "ask": 0.5, "mid": 0.25, "last": 0}
        ]
        result = calculate_roll_options(current, target_quotes, 1.0)
        assert len(result) == 0


class TestGenerateReport:
    """Tests for roll analysis report generation."""

    def test_basic_report(self):
        future = datetime.now() + timedelta(days=30)
        expiry = future.strftime("%Y%m%d")
        current_position = {
            "strike": 100,
            "expiry": expiry,
            "right": "C",
            "quantity": -5,
            "avg_cost": 2.0,
        }
        current_quote = {"bid": 1.0, "ask": 1.50, "mid": 1.25}
        roll_data = {
            expiry: [
                {
                    "strike": 110,
                    "expiry": expiry,
                    "sell_price": 2.50,
                    "buy_price": 1.50,
                    "net": 1.00,
                    "net_type": "credit",
                }
            ],
        }
        report = generate_report("AAPL", 105.0, current_position, current_quote, roll_data)
        assert "Roll Analysis Report: AAPL" in report
        assert "Current Short Position" in report
        assert "Roll Candidates" in report

    def test_no_credit_rolls(self):
        future = datetime.now() + timedelta(days=30)
        expiry = future.strftime("%Y%m%d")
        current_position = {
            "strike": 100,
            "expiry": expiry,
            "right": "C",
            "quantity": -1,
            "avg_cost": 2.0,
        }
        current_quote = {"bid": 5.0, "ask": 5.50, "mid": 5.25}
        roll_data = {}
        report = generate_report("AAPL", 105.0, current_position, current_quote, roll_data)
        assert "No credit rolls available" in report

    def test_with_earnings_date(self):
        future = datetime.now() + timedelta(days=30)
        expiry = future.strftime("%Y%m%d")
        current_position = {
            "strike": 100,
            "expiry": expiry,
            "right": "C",
            "quantity": -1,
            "avg_cost": 2.0,
        }
        current_quote = {"bid": 1.0, "ask": 1.50, "mid": 1.25}
        report = generate_report("AAPL", 105.0, current_position, current_quote, {}, "2025-03-15")
        assert "Earnings Date" in report


class TestGenerateSpreadShortReport:
    """Tests for vertical spread short report."""

    def test_basic_report(self):
        future = datetime.now() + timedelta(days=60)
        expiry = future.strftime("%Y%m%d")
        long_option = {
            "quantity": 5,
            "strike": 100.0,
            "expiry": expiry,
            "avg_cost": 15.0,
        }
        candidates_by_expiry = {
            expiry: [
                {
                    "strike": 120.0,
                    "expiry": expiry,
                    "bid": 3.0,
                    "ask": 3.50,
                    "otm_pct": 14.3,
                    "score": 35,
                    "days": 60,
                }
            ],
        }
        report = generate_spread_short_report("AAPL", 105.0, long_option, candidates_by_expiry, "C")
        assert "Vertical Spread Analysis: AAPL" in report
        assert "Current Long Call Position" in report

    def test_no_candidates(self):
        future = datetime.now() + timedelta(days=60)
        expiry = future.strftime("%Y%m%d")
        long_option = {
            "quantity": 5,
            "strike": 100.0,
            "expiry": expiry,
            "avg_cost": 15.0,
        }
        report = generate_spread_short_report("AAPL", 105.0, long_option, {}, "C")
        assert "No suitable short options found" in report


class TestGenerateNewShortReport:
    """Tests for covered call/put report."""

    def test_covered_call_report(self):
        future = datetime.now() + timedelta(days=30)
        expiry = future.strftime("%Y%m%d")
        long_position = {"quantity": 500, "avg_cost": 100.0}
        candidates_by_expiry = {
            expiry: [
                {
                    "strike": 110.0,
                    "expiry": expiry,
                    "bid": 2.0,
                    "ask": 2.50,
                    "otm_pct": 10.0,
                    "annual_return": 24.3,
                    "score": 35,
                    "days": 30,
                }
            ],
        }
        report = generate_new_short_report("AAPL", 105.0, long_position, candidates_by_expiry, "C")
        assert "New Short Position Analysis: AAPL" in report
        assert "Covered Call" in report
        assert "500" in report  # shares

    def test_no_candidates(self):
        long_position = {"quantity": 500, "avg_cost": 100.0}
        report = generate_new_short_report("AAPL", 105.0, long_position, {}, "C")
        assert "No suitable short options found" in report

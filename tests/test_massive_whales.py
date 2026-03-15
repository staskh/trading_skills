# ABOUTME: Integration tests for option_whales using real Polygon (massive) API.
# ABOUTME: Validates per-second outlier detection by investment for a specific option contract.

from datetime import date

import pandas as pd

from trading_skills.massive.whales import option_whales

# NVDA 170p 2026-03-20 — high-volume contract from known trading session
TEST_CONTRACT = "O:NVDA260320P00170000"
TEST_DATE = date(2026, 3, 13)

REQUIRED_COLUMNS = {"timestamp", "volume", "vwap", "investment", "open", "high", "low", "close"}


class TestOptionWhales:
    def test_returns_dataframe(self):
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE)
        assert isinstance(result, pd.DataFrame)

    def test_required_columns_present(self):
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE)
        assert not result.empty, "Expected at least one whale second for high-volume contract"
        for col in REQUIRED_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_sorted_by_investment_descending(self):
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE)
        if len(result) > 1:
            investments = result["investment"].tolist()
            assert investments == sorted(investments, reverse=True)

    def test_all_investments_positive(self):
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE)
        assert (result["investment"] > 0).all()

    def test_accepts_string_date(self):
        result = option_whales(TEST_CONTRACT, trading_date="2026-03-13")
        assert isinstance(result, pd.DataFrame)

    def test_higher_sigma_returns_fewer_outliers(self):
        low_sigma = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, sigma=3)
        high_sigma = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, sigma=6)
        assert len(low_sigma) >= len(high_sigma)

    def test_unknown_contract_returns_empty(self):
        result = option_whales("O:FAKEXYZ000000C00000000", trading_date=TEST_DATE)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

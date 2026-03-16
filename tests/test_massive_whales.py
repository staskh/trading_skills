# ABOUTME: Integration tests for option_whales using real Polygon (massive) API.
# ABOUTME: Validates per-second outlier detection by invested for a specific option contract.

from datetime import date

import pandas as pd

from trading_skills.massive.whales import option_whales

# NVDA 170p 2026-03-20 — high-volume contract from known trading session
TEST_CONTRACT = "O:NVDA260320P00170000"
TEST_DATE = date(2026, 3, 13)

REQUIRED_COLUMNS = {"timestamp", "volume", "vwap", "invested", "open", "high", "low", "close"}


class TestOptionWhales:
    def test_returns_dataframe(self):
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE)
        assert isinstance(result, pd.DataFrame)

    def test_required_columns_present(self):
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE)
        assert not result.empty, "Expected at least one whale second for high-volume contract"
        for col in REQUIRED_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_all_investeds_positive(self):
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE)
        assert (result["invested"] > 0).all()

    def test_accepts_string_date(self):
        result = option_whales(TEST_CONTRACT, trading_date="2026-03-13")
        assert isinstance(result, pd.DataFrame)

    def test_higher_sigma_returns_fewer_outliers(self):
        low_sigma = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, sigma=2.0)
        high_sigma = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, sigma=5.0)
        assert len(low_sigma) >= len(high_sigma)

    def test_higher_sigma_z_returns_fewer_outliers(self):
        low_sigma_z = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, sigma_z=2.0)
        high_sigma_z = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, sigma_z=5.0)
        assert len(low_sigma_z) >= len(high_sigma_z)

    def test_unknown_contract_returns_empty(self):
        result = option_whales("O:FAKEXYZ000000C00000000", trading_date=TEST_DATE)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_return_all_gives_tuple(self):
        outliers, all_bars = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, return_all=True)
        assert isinstance(outliers, pd.DataFrame)
        assert isinstance(all_bars, pd.DataFrame)
        assert len(all_bars) >= len(outliers)
        assert set(outliers.columns) == set(all_bars.columns)

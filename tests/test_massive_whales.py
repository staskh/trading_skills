# ABOUTME: Integration tests for option_whales using real Polygon (massive) API.
# ABOUTME: Validates per-second outlier detection by invested for a specific option contract.

import os
from datetime import date

import pandas as pd
import pytest

from trading_skills.massive.whales import option_whales

requires_massive = pytest.mark.skipif(
    not os.getenv("MASSIVE_API_KEY"),
    reason="MASSIVE_API_KEY not set",
)

# NVDA 170p 2026-03-20 — high-volume contract from known trading session
TEST_CONTRACT = "O:NVDA260320P00170000"
TEST_DATE = date(2026, 3, 13)

# HOOD 110p 2026-03-20 — contract with known $1M+ single-transaction blocks
TX_CONTRACT = "O:HOOD260320P00110000"

REQUIRED_COLUMNS = {
    "timestamp",
    "ticker",
    "type",
    "strike",
    "expiry",
    "close",
    "volume",
    "transactions",
    "invested",
    "break_even",
}


@requires_massive
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

    def test_low_per_transaction_bars_never_whale(self):
        """Bars averaging <= $50k per transaction must not appear as whales."""
        result = option_whales(TEST_CONTRACT, trading_date=TEST_DATE, sigma_z=0.5)
        for _, row in result.iterrows():
            if row["transactions"] and row["transactions"] > 0:
                avg = row["invested"] / row["transactions"]
                assert avg > 50_000, f"Whale with avg invested/tx = {avg:.0f} <= $50k"

    def test_large_per_transaction_bars_always_detected(self):
        """Bars with avg invested/transaction >= $1M are whales regardless of sigma_z."""
        _, all_bars = option_whales(TX_CONTRACT, trading_date=TEST_DATE, return_all=True)
        qualifying = all_bars[
            all_bars["transactions"].notna()
            & (all_bars["transactions"] > 0)
            & (all_bars["invested"] / all_bars["transactions"] >= 1_000_000)
        ]
        if qualifying.empty:
            pytest.skip("No bars with avg invested/tx >= $1M in test data")
        # With sigma_z=1000 statistical detection is off — per-tx rule must still fire
        result = option_whales(TX_CONTRACT, trading_date=TEST_DATE, sigma_z=1000)
        assert not result.empty
        for ts in qualifying["timestamp"]:
            assert ts in result["timestamp"].tolist()

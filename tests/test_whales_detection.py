# ABOUTME: Unit tests for the per-second whale detection rule applied to option bars.
# ABOUTME: Covers the outlier test, the $1M block rule, the $50k noise floor and thin contracts.

import pandas as pd

from trading_skills.massive.whales import _whale_mask


def _bars(invested, transactions=None):
    transactions = transactions or [1] * len(invested)
    return pd.DataFrame({"invested": invested, "transactions": transactions})


class TestThinContracts:
    def test_block_above_min_order_is_whale(self):
        mask = _whale_mask(_bars([1_000.0, 250_000.0]), sigma_z=3.5)
        assert list(mask) == [False, True]

    def test_single_bar_above_min_order_is_whale(self):
        assert list(_whale_mask(_bars([60_000.0]), sigma_z=3.5)) == [True]

    def test_unknown_transaction_count_uses_bar_invested(self):
        bars = pd.DataFrame({"invested": [1_000.0, 250_000.0], "transactions": [None, None]})
        assert list(_whale_mask(bars, sigma_z=3.5)) == [False, True]

    def test_many_small_trades_are_not_whale(self):
        mask = _whale_mask(_bars([1_000.0, 250_000.0], transactions=[1, 10]), sigma_z=3.5)
        assert list(mask) == [False, False]


class TestLiquidContracts:
    def test_min_order_alone_is_not_whale(self):
        invested = [10_000.0 * i for i in range(1, 13)]
        mask = _whale_mask(_bars(invested), sigma_z=3.5)
        assert not mask.any()

    def test_outlier_above_min_order_is_whale(self):
        invested = [1_000.0] * 5 + [1_200.0] * 5 + [80_000.0]
        mask = _whale_mask(_bars(invested), sigma_z=3.5)
        assert list(mask) == [False] * 10 + [True]

    def test_outlier_of_small_trades_is_not_whale(self):
        invested = [1_000.0] * 5 + [1_200.0] * 5 + [80_000.0]
        transactions = [1] * 10 + [4]
        mask = _whale_mask(_bars(invested, transactions), sigma_z=3.5)
        assert not mask.any()

    def test_million_dollar_block_is_whale(self):
        invested = [10_000.0 * i for i in range(1, 13)] + [1_000_000.0]
        mask = _whale_mask(_bars(invested), sigma_z=1_000)
        assert list(mask) == [False] * 12 + [True]

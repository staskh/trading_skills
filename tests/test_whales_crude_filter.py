# ABOUTME: Unit tests for the crude filter used in whale detection.
# ABOUTME: Validates MAD-based z-score detects high-volume cheap options missed by std.

import numpy as np
import pandas as pd
import pytest

from trading_skills.massive.whales import _modified_z_score


class TestCrudeFilter:
    @pytest.fixture
    def skewed_invested(self):
        """Right-skewed distribution mimicking real options data.

        300 typical contracts ($1k–$50k invested), 10 high-dollar contracts
        ($200k–$800k, e.g. NVDA/SPY), and one cheap-but-high-volume whale
        like HTZ: 14,000 contracts × $0.10 × 100 = $140k.
        """
        rng = np.random.default_rng(42)
        typical = rng.uniform(1_000, 50_000, 300)
        high_dollar = rng.uniform(200_000, 800_000, 10)
        whale = np.array([140_000.0])
        return pd.Series(np.concatenate([typical, high_dollar, whale]))

    def test_detects_high_volume_cheap_option(self, skewed_invested):
        """Whale ($140k) must be flagged despite high-dollar contracts inflating spread."""
        mask = _modified_z_score(skewed_invested, sigma_z=3.5)
        assert mask.iloc[-1], "HTZ-like whale should be detected by MAD-based z-score"

    def test_std_based_would_miss_whale(self, skewed_invested):
        """Documents the bug: median + 3*std threshold exceeds $140k when std is inflated."""
        median = skewed_invested.median()
        threshold = median + 3.0 * skewed_invested.std()
        assert not (skewed_invested.iloc[-1] > threshold), (
            "Regression check: std-based approach should miss this whale (proving the bug exists)"
        )

    def test_mad_zero_falls_back_to_above_median(self):
        """All-equal series: everything at median has z=0; only values above median pass."""
        equal = pd.Series([100.0] * 10)
        mask = _modified_z_score(equal, sigma_z=3.5)
        assert not mask.any()

    def test_clear_outlier_always_detected(self):
        """Unambiguous outlier (100× median) is always flagged."""
        data = pd.Series([100.0] * 50 + [10_000.0])
        mask = _modified_z_score(data, sigma_z=3.5)
        assert mask.iloc[-1]

    def test_returns_boolean_series(self, skewed_invested):
        mask = _modified_z_score(skewed_invested, sigma_z=3.5)
        assert isinstance(mask, pd.Series)
        assert mask.dtype == bool

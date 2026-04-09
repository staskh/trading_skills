# ABOUTME: Unit tests for _modified_z_score — the unified outlier detection function.
# ABOUTME: Verifies MAD-based detection works for both small and large samples.

import inspect

import numpy as np
import pandas as pd

from trading_skills.massive.whales import _modified_z_score, option_whales


class TestModifiedZScore:
    def test_clear_outlier_detected(self):
        data = pd.Series([100.0] * 50 + [10_000.0])
        assert _modified_z_score(data, sigma_z=3.5).iloc[-1]

    def test_non_outlier_not_detected(self):
        rng = np.random.default_rng(42)
        data = pd.Series(rng.uniform(100, 200, 100))
        # median value should not be flagged
        median_val = float(data.median())
        data = pd.concat([data, pd.Series([median_val])], ignore_index=True)
        assert not _modified_z_score(data, sigma_z=3.5).iloc[-1]

    def test_large_sample_uses_mad_not_std(self):
        """With n >= 30 and a right-skewed distribution, MAD catches what std misses."""
        rng = np.random.default_rng(42)
        typical = rng.uniform(1_000, 50_000, 300)
        high_dollar = rng.uniform(200_000, 800_000, 10)
        whale = np.array([140_000.0])
        data = pd.Series(np.concatenate([typical, high_dollar, whale]))

        mask = _modified_z_score(data, sigma_z=3.5)
        assert mask.iloc[-1], "MAD-based detection should catch whale in large skewed sample"

        # Verify std-based would miss it (documents the old behavior)
        median = data.median()
        std_threshold = median + 3.0 * data.std()
        assert not (data.iloc[-1] > std_threshold), "std-based misses it (regression proof)"

    def test_mad_zero_all_equal_returns_no_outliers(self):
        """When all values are equal, none are above the median — no outliers flagged."""
        data = pd.Series([500.0] * 20)
        assert not _modified_z_score(data, sigma_z=3.5).any()

    def test_mad_zero_with_lone_outlier_is_detected(self):
        """Lone outlier in a sea of equal values has MAD=0 but is above median — flagged."""
        data = pd.Series([100.0] * 50 + [10_000.0])
        assert _modified_z_score(data, sigma_z=3.5).iloc[-1]

    def test_returns_boolean_series(self):
        data = pd.Series([1.0, 2.0, 100.0])
        result = _modified_z_score(data, sigma_z=3.5)
        assert isinstance(result, pd.Series)
        assert result.dtype == bool


class TestOptionWhalesNoSigma:
    def test_sigma_parameter_removed(self):
        """option_whales must not accept a sigma kwarg."""
        sig = inspect.signature(option_whales)
        assert "sigma" not in sig.parameters, "sigma parameter should be removed from option_whales"

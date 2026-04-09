# ABOUTME: Unit tests for the crude candidate selection in whale hunting.
# ABOUTME: Verifies OR-selection logic (z-score OR volume>OI) and reason/OI columns.

import numpy as np
import pandas as pd

from trading_skills.massive.whales import _apply_crude_selection


def _make_active(records):
    """Build a minimal active DataFrame from list of dicts."""
    defaults = {"volume": 100, "openInterest": 200, "invested": 1_000.0}
    rows = [{**defaults, **r} for r in records]
    return pd.DataFrame(rows)


class TestApplyCrudeSelection:
    def test_zscore_outlier_selected_with_reason_zscore(self):
        """High invested z-score → reason='z_score'."""
        active = _make_active(
            # 50 normal rows + 1 clear z-score outlier, all volume < OI
            [{"invested": 1_000.0, "volume": 10, "openInterest": 500}] * 50
            + [{"invested": 500_000.0, "volume": 10, "openInterest": 500}]
        )
        result = _apply_crude_selection(active, sigma_z=3.5)
        outlier = result[result["invested"] == 500_000.0]
        assert len(outlier) == 1
        assert outlier.iloc[0]["reason"] == "z_score"

    def test_volume_gt_oi_selected_with_reason_volume_oi(self):
        """Volume > OI → reason='volume>oi', even if invested is unremarkable."""
        rng = np.random.default_rng(0)
        # Real spread so MAD > 0; the volume>OI row is at median invested level
        invested_vals = rng.uniform(500, 2_000, 50).tolist()
        median_inv = float(np.median(invested_vals))
        rows = [{"invested": v, "volume": 10, "openInterest": 500} for v in invested_vals]
        rows.append({"invested": median_inv, "volume": 600, "openInterest": 500})
        active = _make_active(rows)
        result = _apply_crude_selection(active, sigma_z=3.5)
        vol_oi = result[result["volume"] == 600]
        assert len(vol_oi) == 1
        assert vol_oi.iloc[0]["reason"] == "volume>oi"

    def test_both_conditions_gives_reason_both(self):
        """High z-score AND volume > OI → reason='both'."""
        rows = [{"invested": 1_000.0, "volume": 10, "openInterest": 500}] * 50
        rows.append({"invested": 500_000.0, "volume": 600, "openInterest": 500})
        active = _make_active(rows)
        result = _apply_crude_selection(active, sigma_z=3.5)
        both = result[result["volume"] == 600]
        assert len(both) == 1
        assert both.iloc[0]["reason"] == "both"

    def test_neither_condition_excluded(self):
        """Row with average invested and volume < OI is not selected."""
        active = _make_active([{"invested": 1_000.0, "volume": 10, "openInterest": 500}] * 20)
        result = _apply_crude_selection(active, sigma_z=3.5)
        assert result.empty

    def test_open_interest_column_present(self):
        """Result must have open_interest column mapped from openInterest."""
        rows = [{"invested": 1_000.0, "volume": 10, "openInterest": 500}] * 50
        rows.append({"invested": 500_000.0, "volume": 10, "openInterest": 123})
        active = _make_active(rows)
        result = _apply_crude_selection(active, sigma_z=3.5)
        assert "open_interest" in result.columns
        assert result[result["invested"] == 500_000.0].iloc[0]["open_interest"] == 123

    def test_nan_open_interest_handled(self):
        """NaN openInterest → volume>OI condition is False (not selected on that basis)."""
        rows = [{"invested": 1_000.0, "volume": 10, "openInterest": 500}] * 50
        rows.append({"invested": 500_000.0, "volume": 600, "openInterest": float("nan")})
        active = _make_active(rows)
        result = _apply_crude_selection(active, sigma_z=3.5)
        nan_row = result[result["volume"] == 600]
        # selected by z_score, not volume>OI (OI is NaN)
        assert nan_row.iloc[0]["reason"] == "z_score"

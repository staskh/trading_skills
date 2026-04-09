# ABOUTME: Unit tests for parallel precise whale fetch.
# ABOUTME: Verifies result aggregation and exception isolation across candidates.

from datetime import date
from unittest.mock import patch

import pandas as pd

from trading_skills.massive.whales import _WHALE_COLS, _fetch_whales_parallel


def _make_candidates(*symbols, open_interest=123, reason="z_score"):
    return pd.DataFrame(
        [
            {
                "contractSymbol": s,
                "tradeDate": date(2026, 4, 7),
                "open_interest": open_interest,
                "reason": reason,
            }
            for s in symbols
        ]
    )


def _whale_df(symbol):
    row = {col: None for col in _WHALE_COLS}
    row["ticker"] = symbol
    return pd.DataFrame([row])


class TestFetchWhalesParallel:
    def test_returns_results_for_all_candidates(self):
        candidates = _make_candidates("HTZ260515C00007500", "NVDA260320P00170000")
        side_effects = [_whale_df("HTZ260515C00007500"), _whale_df("NVDA260320P00170000")]
        with patch("trading_skills.massive.whales.option_whales", side_effect=side_effects):
            result = _fetch_whales_parallel(candidates, sigma_z=3.5)
        assert len(result) == 2

    def test_exception_in_one_candidate_does_not_abort_others(self):
        candidates = _make_candidates("BAD", "GOOD260515C00007500")
        good_df = _whale_df("GOOD260515C00007500")

        def side_effect(ticker, **kwargs):
            if "BAD" in ticker:
                raise RuntimeError("API error")
            return good_df

        with patch("trading_skills.massive.whales.option_whales", side_effect=side_effect):
            result = _fetch_whales_parallel(candidates, sigma_z=3.5)
        assert len(result) == 1
        assert result[0]["ticker"].iloc[0] == "GOOD260515C00007500"

    def test_skips_empty_dataframes(self):
        candidates = _make_candidates("EMPTY", "FULL260515C00007500")
        empty_df = pd.DataFrame(columns=_WHALE_COLS)
        full_df = _whale_df("FULL260515C00007500")

        with patch("trading_skills.massive.whales.option_whales", side_effect=[empty_df, full_df]):
            result = _fetch_whales_parallel(candidates, sigma_z=3.5)
        assert len(result) == 1

    def test_all_empty_returns_empty_list(self):
        candidates = _make_candidates("A", "B")
        empty_df = pd.DataFrame(columns=_WHALE_COLS)
        with patch("trading_skills.massive.whales.option_whales", return_value=empty_df):
            result = _fetch_whales_parallel(candidates, sigma_z=3.5)
        assert result == []

    def test_open_interest_and_reason_propagated_from_candidate(self):
        """open_interest and reason from the crude step carry through to precise output."""
        candidates = _make_candidates("HTZ260515C00007500", open_interest=14000, reason="both")
        whale_df = _whale_df("HTZ260515C00007500")
        with patch("trading_skills.massive.whales.option_whales", return_value=whale_df):
            result = _fetch_whales_parallel(candidates, sigma_z=3.5)
        assert len(result) == 1
        assert result[0]["open_interest"].iloc[0] == 14000
        assert result[0]["reason"].iloc[0] == "both"

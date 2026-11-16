# ABOUTME: Tests whales_hunter's Yahoo fallback, two-session window, and JSON-safe records.
# ABOUTME: Uses real Yahoo Finance chains; the Massive drill-down is bypassed or absent.

import json
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading_skills.massive.whales import _to_records, whales_hunter
from trading_skills.utils import latest_trading_date, previous_trading_date

TEST_UNDERLYING = "NVDA"


class TestToRecords:
    def test_missing_values_become_none(self):
        df = pd.DataFrame({"spot": [np.nan, 101.5], "pct_from_spot": [np.nan, 2.0]})
        assert _to_records(df) == [
            {"spot": None, "pct_from_spot": None},
            {"spot": 101.5, "pct_from_spot": 2.0},
        ]

    def test_records_serialize_as_strict_json(self):
        df = pd.DataFrame({"volume": [10, 20], "spot": [np.nan, 1.0]})
        json.dumps(_to_records(df), allow_nan=False)


class TestYahooFallback:
    def test_missing_key_falls_back_to_yahoo(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        result = whales_hunter(TEST_UNDERLYING, precise=True)
        assert result["source"] == "yahoo"
        assert len(result["whales"]) > 0

    def test_no_massive_results_falls_back_to_yahoo(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "present")
        with patch("trading_skills.massive.whales._fetch_whales_parallel", return_value=[]):
            result = whales_hunter(TEST_UNDERLYING, precise=True)
        assert result["source"] == "yahoo"
        assert len(result["whales"]) > 0


class TestWindowDates:
    def test_window_is_previous_and_latest_session(self):
        result = whales_hunter(TEST_UNDERLYING, precise=False)
        latest = latest_trading_date()
        assert result["window_dates"] == [previous_trading_date(latest), latest]

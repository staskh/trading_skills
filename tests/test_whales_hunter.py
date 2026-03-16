# ABOUTME: Integration tests for whales_hunter using real Yahoo Finance + Polygon APIs.
# ABOUTME: Validates two-step whale detection: crude Yahoo scan + precise Polygon drill-down.

from datetime import date

import pytest

from trading_skills.massive.whales import whales_hunter

# HOOD on 2026-03-13 had known heavy put whale activity
TEST_UNDERLYING = "HOOD"
TEST_DATE = date(2026, 3, 13)

REQUIRED_FIELDS = {
    "timestamp", "ticker", "type", "strike", "expiry",
    "close", "volume", "transactions", "invested", "break_even",
}


class TestWhalesHunter:
    def test_returns_dict_with_required_keys(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=False)
        assert isinstance(result, dict)
        assert "whales" in result
        assert "source" in result

    def test_whales_is_list(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=False)
        assert isinstance(result["whales"], list)

    def test_yahoo_only_mode_sets_source(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=False)
        assert result["source"] == "yahoo only"

    def test_known_active_underlying_returns_whales(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=False)
        assert len(result["whales"]) > 0

    def test_whale_dict_has_required_fields(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=False)
        assert len(result["whales"]) > 0
        for field in REQUIRED_FIELDS:
            assert field in result["whales"][0], f"Missing field: {field}"

    def test_invalid_underlying_returns_empty(self):
        result = whales_hunter("INVALIDXYZ123", trading_date=TEST_DATE, precise=False)
        assert result["whales"] == []

    def test_precise_mode_source_is_massive_or_yahoo(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=True)
        assert result["source"] in ("massive", "yahoo only")

    def test_precise_mode_returns_whales(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=True)
        assert len(result["whales"]) > 0

    def test_precise_mode_source_is_massive(self):
        result = whales_hunter(TEST_UNDERLYING, trading_date=TEST_DATE, precise=True)
        assert result["source"] == "massive"

# ABOUTME: Tests for shared utility functions.
# ABOUTME: Covers type conversion, price extraction, date formatting, and volatility helpers.

import asyncio
import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from trading_skills.utils import (
    annualized_volatility,
    days_to_expiry,
    fetch_with_timeout,
    format_expiry_iso,
    format_expiry_long,
    format_expiry_short,
    get_current_price,
    safe_value,
)


class TestSafeValue:
    """Tests for safe_value type conversion."""

    def test_none_returns_none(self):
        assert safe_value(None) is None

    def test_nan_returns_none(self):
        assert safe_value(float("nan")) is None

    def test_numpy_nan_returns_none(self):
        assert safe_value(np.nan) is None

    def test_pandas_nat_returns_none(self):
        assert safe_value(pd.NaT) is None

    def test_numpy_int64(self):
        val = np.int64(42)
        result = safe_value(val)
        assert result == 42
        assert isinstance(result, int)

    def test_numpy_float64(self):
        val = np.float64(3.14)
        result = safe_value(val)
        assert result == pytest.approx(3.14)
        assert isinstance(result, float)

    def test_regular_int_passthrough(self):
        assert safe_value(42) == 42

    def test_regular_float_passthrough(self):
        assert safe_value(3.14) == 3.14

    def test_string_passthrough(self):
        assert safe_value("hello") == "hello"

    def test_zero_not_none(self):
        assert safe_value(0) == 0
        assert safe_value(0.0) == 0.0


class TestFetchWithTimeout:
    """Tests for async fetch_with_timeout."""

    def test_successful_coroutine(self):
        async def quick():
            return "done"

        result = asyncio.run(fetch_with_timeout(quick(), timeout=5.0))
        assert result == "done"

    def test_timeout_returns_default(self):
        async def slow():
            await asyncio.sleep(10)
            return "done"

        result = asyncio.run(fetch_with_timeout(slow(), timeout=0.1, default="timed_out"))
        assert result == "timed_out"

    def test_exception_returns_default(self):
        async def failing():
            raise ValueError("boom")

        result = asyncio.run(fetch_with_timeout(failing(), timeout=5.0, default="failed"))
        assert result == "failed"

    def test_default_is_none(self):
        async def failing():
            raise RuntimeError("error")

        result = asyncio.run(fetch_with_timeout(failing(), timeout=5.0))
        assert result is None


class TestGetCurrentPrice:
    """Tests for get_current_price extraction."""

    def test_current_price_preferred(self):
        info = {"currentPrice": 150.0, "regularMarketPrice": 145.0}
        assert get_current_price(info) == 150.0

    def test_fallback_to_regular_market(self):
        info = {"regularMarketPrice": 145.0}
        assert get_current_price(info) == 145.0

    def test_none_current_price_falls_back(self):
        info = {"currentPrice": None, "regularMarketPrice": 145.0}
        assert get_current_price(info) == 145.0

    def test_empty_dict_returns_none(self):
        assert get_current_price({}) is None

    def test_both_none_returns_none(self):
        info = {"currentPrice": None, "regularMarketPrice": None}
        assert get_current_price(info) is None


class TestDaysToExpiry:
    """Tests for days_to_expiry calculation."""

    def test_future_date(self):
        future = datetime.now() + timedelta(days=30)
        expiry_str = future.strftime("%Y%m%d")
        days = days_to_expiry(expiry_str)
        assert 29 <= days <= 31

    def test_past_date(self):
        past = datetime.now() - timedelta(days=10)
        expiry_str = past.strftime("%Y%m%d")
        days = days_to_expiry(expiry_str)
        assert days < 0

    def test_invalid_returns_999(self):
        assert days_to_expiry("invalid") == 999


class TestAnnualizedVolatility:
    """Tests for annualized_volatility calculation."""

    def test_basic_calculation(self):
        np.random.seed(42)
        prices = pd.Series(100 + np.cumsum(np.random.randn(60) * 2))
        returns, daily_vol, annual_vol = annualized_volatility(prices)
        assert len(returns) == 59
        assert daily_vol > 0
        assert annual_vol == pytest.approx(daily_vol * math.sqrt(252))

    def test_constant_prices(self):
        prices = pd.Series([100.0] * 30)
        returns, daily_vol, annual_vol = annualized_volatility(prices)
        assert daily_vol == 0.0
        assert annual_vol == 0.0


class TestFormatExpiryIso:
    """Tests for YYYYMMDD -> YYYY-MM-DD formatting."""

    def test_valid(self):
        assert format_expiry_iso("20250321") == "2025-03-21"

    def test_short_string_passthrough(self):
        assert format_expiry_iso("2025") == "2025"


class TestFormatExpiryLong:
    """Tests for YYYYMMDD -> 'Mon DD, YYYY' formatting."""

    def test_valid(self):
        assert format_expiry_long("20250321") == "Mar 21, 2025"

    def test_invalid_returns_original(self):
        assert format_expiry_long("invalid") == "invalid"


class TestFormatExpiryShort:
    """Tests for YYYYMMDD -> 'Mon DD' formatting."""

    def test_valid(self):
        assert format_expiry_short("20250321") == "Mar 21"

    def test_empty_returns_dash(self):
        assert format_expiry_short("") == "-"

    def test_none_returns_dash(self):
        assert format_expiry_short(None) == "-"

    def test_invalid_returns_original(self):
        assert format_expiry_short("invalid") == "invalid"

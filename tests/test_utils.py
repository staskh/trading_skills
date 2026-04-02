# ABOUTME: Tests for shared utility functions.
# ABOUTME: Covers type coercion, price extraction, date helpers, volatility, and NYSE calendar.

import asyncio
import math
from datetime import date, datetime, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from trading_skills.utils import (
    _coerce_date,
    annualized_volatility,
    days_to_expiry,
    fetch_with_timeout,
    format_expiry_iso,
    format_expiry_long,
    format_expiry_short,
    get_current_price,
    is_trading_now,
    latest_trading_date,
    previous_trading_date,
    safe_value,
    trading_sessions,
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


class TestCoerceDate:
    def test_date_passthrough(self):
        d = date(2025, 3, 21)
        assert _coerce_date(d) == d

    def test_datetime(self):
        assert _coerce_date(datetime(2025, 3, 21, 10, 0)) == date(2025, 3, 21)

    def test_iso_string(self):
        assert _coerce_date("2025-03-21") == date(2025, 3, 21)

    def test_yyyymmdd_string(self):
        assert _coerce_date("20250321") == date(2025, 3, 21)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            _coerce_date("not-a-date")


class TestIsTradingNow:
    def test_true_during_market_hours(self):
        # Wednesday 2025-03-19 11:00 ET — normal trading day, midday
        ET = pytest.importorskip("zoneinfo").ZoneInfo("America/New_York")
        market_time = datetime(2025, 3, 19, 11, 0, tzinfo=ET)
        with patch("trading_skills.utils.datetime") as mock_dt:
            mock_dt.now.return_value = market_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = is_trading_now()
        assert result is True

    def test_false_on_weekend(self):
        # Saturday 2025-03-22
        ET = pytest.importorskip("zoneinfo").ZoneInfo("America/New_York")
        weekend = datetime(2025, 3, 22, 11, 0, tzinfo=ET)
        with patch("trading_skills.utils.datetime") as mock_dt:
            mock_dt.now.return_value = weekend
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = is_trading_now()
        assert result is False

    def test_false_before_open(self):
        # Wednesday 2025-03-19 8:00 ET — before open
        ET = pytest.importorskip("zoneinfo").ZoneInfo("America/New_York")
        before_open = datetime(2025, 3, 19, 8, 0, tzinfo=ET)
        with patch("trading_skills.utils.datetime") as mock_dt:
            mock_dt.now.return_value = before_open
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = is_trading_now()
        assert result is False


class TestLatestTradingDate:
    def test_returns_today_during_market_hours(self):
        # Wednesday 2025-03-19 11:00 ET
        ny = pytest.importorskip("zoneinfo").ZoneInfo("America/New_York")
        market_time = datetime(2025, 3, 19, 11, 0, tzinfo=ny)
        with patch("trading_skills.utils.datetime") as mock_dt:
            mock_dt.now.return_value = market_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = latest_trading_date()
        assert result == date(2025, 3, 19)

    def test_returns_friday_on_saturday(self):
        # Saturday 2025-03-22 → should return Friday 2025-03-21
        ny = pytest.importorskip("zoneinfo").ZoneInfo("America/New_York")
        weekend = datetime(2025, 3, 22, 11, 0, tzinfo=ny)
        with patch("trading_skills.utils.datetime") as mock_dt:
            mock_dt.now.return_value = weekend
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            result = latest_trading_date()
        assert result == date(2025, 3, 21)


class TestTradingSessions:
    def test_known_week(self):
        # 2025-03-17 (Mon) to 2025-03-21 (Fri) — 5 sessions
        sessions = trading_sessions("2025-03-17", "2025-03-21")
        assert len(sessions) == 5
        assert sessions[0] == date(2025, 3, 17)
        assert sessions[-1] == date(2025, 3, 21)

    def test_skips_weekend(self):
        sessions = trading_sessions("2025-03-21", "2025-03-24")
        # Fri + Mon = 2 sessions (Sat/Sun skipped)
        assert date(2025, 3, 22) not in sessions
        assert date(2025, 3, 23) not in sessions

    def test_skips_holiday(self):
        # Good Friday 2025-04-18 is NYSE holiday
        sessions = trading_sessions("2025-04-17", "2025-04-22")
        assert date(2025, 4, 18) not in sessions

    def test_accepts_date_objects(self):
        sessions = trading_sessions(date(2025, 3, 17), date(2025, 3, 19))
        assert len(sessions) == 3

    def test_accepts_datetime_objects(self):
        sessions = trading_sessions(datetime(2025, 3, 17, 9, 0), datetime(2025, 3, 19, 16, 0))
        assert len(sessions) == 3

    def test_sorted_ascending(self):
        sessions = trading_sessions("2025-03-17", "2025-03-21")
        assert sessions == sorted(sessions)

    def test_to_none_uses_today(self):
        # Just verify it doesn't raise and returns a list
        sessions = trading_sessions("2025-03-17")
        assert isinstance(sessions, list)
        assert all(isinstance(s, date) for s in sessions)


class TestPreviousTradingDate:
    def test_monday_returns_friday(self):
        # 2026-03-16 is Monday, previous trading day is 2026-03-13 (Friday)
        assert previous_trading_date(date(2026, 3, 16)) == date(2026, 3, 13)

    def test_tuesday_returns_monday(self):
        assert previous_trading_date(date(2026, 3, 17)) == date(2026, 3, 16)

    def test_skips_holiday(self):
        # Good Friday 2025-04-18 is NYSE holiday; previous of 2025-04-21 (Mon) is 2025-04-17 (Thu)
        assert previous_trading_date(date(2025, 4, 21)) == date(2025, 4, 17)

    def test_accepts_string(self):
        assert previous_trading_date("2026-03-17") == date(2026, 3, 16)

    def test_returns_date_type(self):
        result = previous_trading_date(date(2026, 3, 17))
        assert isinstance(result, date)

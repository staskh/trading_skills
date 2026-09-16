# ABOUTME: Tests for the EMA9/EMA21 + VIX/VXN regime strategy.
# ABOUTME: Covers all-IB vol sourcing and the gate refusing to trade without a reading.

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from trading_skills.broker import ema_vix
from trading_skills.broker.ema_vix import NY, _fetch_vol_index, run_ema_vix_strategy

MODULE = "trading_skills.broker.ema_vix"


def _bar(close, dt):
    return SimpleNamespace(close=close, date=dt, open=close, high=close, low=close)


class _FakeIB:
    """Serves historical bars per bar size, or raises for a side that is down."""

    def __init__(self, minute_bars=None, daily_bars=None, fail=()):
        self.minute_bars = minute_bars
        self.daily_bars = daily_bars
        self.fail = fail

    async def qualifyContractsAsync(self, *contracts):
        return list(contracts)

    async def reqHistoricalDataAsync(self, contract, *, barSizeSetting, **kwargs):
        if barSizeSetting in self.fail:
            raise RuntimeError(f"{barSizeSetting} unavailable")
        return (self.minute_bars if barSizeSetting == "1 min" else self.daily_bars) or []


class TestFetchVolIndex:
    """Both vol readings come from IB — no third-party source."""

    @staticmethod
    def _daily(days_back):
        today = datetime.now(NY).date()
        return [_bar(15.0 + i, today - timedelta(days=d)) for i, d in enumerate(days_back)]

    def test_reads_intraday_from_minute_bars(self):
        ib = _FakeIB(minute_bars=[_bar(14.1, None), _bar(16.25, None)], daily_bars=self._daily([1]))
        intraday, _ = asyncio.run(_fetch_vol_index(ib, "VIX"))
        assert intraday == pytest.approx(16.25)

    def test_reads_prior_day_from_daily_bars(self):
        ib = _FakeIB(minute_bars=[_bar(14.1, None)], daily_bars=self._daily([3, 2, 1]))
        _, prior = asyncio.run(_fetch_vol_index(ib, "VIX"))
        assert prior == pytest.approx(17.0)  # last bar before today

    def test_todays_partial_daily_bar_is_not_the_prior_close(self):
        """IB includes today's in-progress daily bar; it is not the prior-day close."""
        today = datetime.now(NY).date()
        ib = _FakeIB(
            minute_bars=[_bar(14.1, None)],
            daily_bars=[_bar(19.0, today - timedelta(days=1)), _bar(99.0, today)],
        )
        _, prior = asyncio.run(_fetch_vol_index(ib, "VIX"))
        assert prior == pytest.approx(19.0)

    def test_accepts_datetime_dated_bars(self):
        """formatDate=2 can yield datetimes rather than dates."""
        yesterday = datetime.now(NY).date() - timedelta(days=1)
        ib = _FakeIB(
            minute_bars=[_bar(14.1, None)],
            daily_bars=[_bar(18.5, datetime(yesterday.year, yesterday.month, yesterday.day))],
        )
        _, prior = asyncio.run(_fetch_vol_index(ib, "VIX"))
        assert prior == pytest.approx(18.5)

    def test_intraday_failure_returns_none(self):
        ib = _FakeIB(daily_bars=self._daily([1]), fail=("1 min",))
        intraday, prior = asyncio.run(_fetch_vol_index(ib, "VIX"))
        assert intraday is None
        assert prior is not None

    def test_daily_failure_returns_none(self):
        ib = _FakeIB(minute_bars=[_bar(14.1, None)], fail=("1 day",))
        intraday, prior = asyncio.run(_fetch_vol_index(ib, "VIX"))
        assert intraday is not None
        assert prior is None

    def test_empty_bars_return_none(self):
        intraday, prior = asyncio.run(_fetch_vol_index(_FakeIB(), "VIX"))
        assert intraday is None
        assert prior is None


class TestNoThirdPartyVolSource:
    """The strategy must not reach outside IB for a reading that gates a live trade."""

    def test_yfinance_is_not_imported(self):
        assert not hasattr(ema_vix, "yf")

    def test_vol_index_mapping_is_ib_only(self):
        assert ema_vix._vol_index_for("NDX") == "VXN"
        assert ema_vix._vol_index_for("SPX") == "VIX"


def _bars(n=40):
    """A rising 30-min series, enough history for the EMA lookback."""
    start = datetime(2026, 9, 10, 13, 30, tzinfo=UTC)
    return [
        {"dt": start + timedelta(minutes=30 * i), "open": 100.0 + i, "close": 100.5 + i}
        for i in range(n)
    ]


class TestVolGateFailsClosed:
    """No vol reading must block the trade, not wave it through."""

    def _run(self, *, intraday, prior, source="ib"):
        async def fake_fetch_bars(*args, **kwargs):
            return _bars(), intraday, prior, source

        with patch(f"{MODULE}._fetch_bars", side_effect=fake_fetch_bars):
            return asyncio.run(run_ema_vix_strategy("SPX", budget=1000, port=7496))

    def test_missing_prior_day_reading_blocks_the_trade(self):
        result = self._run(intraday=15.0, prior=None)
        assert result["success"] is False
        assert result["signal"] == "VOL-UNAVAILABLE"
        assert result["spread_type"] is None

    def test_missing_intraday_reading_blocks_the_trade(self):
        result = self._run(intraday=None, prior=15.0)
        assert result["success"] is False
        assert result["signal"] == "VOL-UNAVAILABLE"

    def test_both_readings_missing_blocks_the_trade(self):
        result = self._run(intraday=None, prior=None, source="unavailable")
        assert result["success"] is False
        assert result["signal"] == "VOL-UNAVAILABLE"

    def test_reason_names_the_missing_side(self):
        assert "prior" in self._run(intraday=15.0, prior=None)["reason"].lower()

    def test_elevated_vol_still_reports_vix_skip(self):
        """The existing skip path must not be swallowed by the guard."""
        result = self._run(intraday=25.0, prior=15.0)
        assert result["success"] is False
        assert result["signal"] == "VIX-SKIP"

    def test_prior_day_alone_can_veto(self):
        """The dual gate blocks a calm morning after a high-vol close."""
        result = self._run(intraday=15.0, prior=25.0)
        assert result["signal"] == "VIX-SKIP"
        assert "prior-day" in result["reason"]

    def test_readings_present_and_calm_passes_the_vol_gate(self):
        result = self._run(intraday=15.0, prior=16.0)
        assert result["signal"] not in ("VOL-UNAVAILABLE", "VIX-SKIP")

    def test_source_is_reported(self):
        assert self._run(intraday=15.0, prior=16.0)["vix_source"] == "ib"


class TestVolIndexDates:
    """Date handling helper used to pick the prior-day bar."""

    def test_date_passthrough(self):
        d = date(2026, 9, 11)
        assert ema_vix._bar_date(_bar(1.0, d)) == d

    def test_datetime_narrows_to_date(self):
        assert ema_vix._bar_date(_bar(1.0, datetime(2026, 9, 11, 16, 15))) == date(2026, 9, 11)


# --------------------------------------------------------------------------- #
# rr_gate bar selection
# --------------------------------------------------------------------------- #
BAR = timedelta(minutes=30)


def _falling_bars(tail, *, now=None):
    """A declining series (so the EMA cross is down) ending in `tail`.

    `tail` is a list of (open, close) for today's most recent bars, oldest first;
    the last entry is stamped as the bar currently in progress.
    """
    now = now or datetime.now(NY)
    history = []
    start = now.astimezone(UTC) - BAR * (60 + len(tail))
    # Rise then fall, so EMA9 actually crosses back down through EMA21.
    for i in range(60):
        price = 100.0 + i if i < 30 else 100.0 + (60 - i) * 2
        history.append({"dt": start + BAR * i, "open": price, "close": price - 0.5})
    # Today's tail: the final bar starts now, so its period has not closed yet.
    first_tail_start = now.astimezone(UTC) - BAR * (len(tail) - 1)
    for i, (o, c) in enumerate(tail):
        history.append({"dt": first_tail_start + BAR * i, "open": o, "close": c})
    return history


class TestRrGateUsesRecentBars:
    """The red->red confirmation must reflect current momentum, not the open."""

    def test_two_most_recent_completed_bars_are_red(self):
        # ... older ..., red, red, then an in-progress bar that is green.
        bars = _falling_bars([(100.0, 99.0), (99.0, 98.0), (98.0, 105.0)])
        spread, signal, reason, _ = ema_vix._detect_signal(bars, rr_gate=True)
        assert signal == "EMA-Dn+RR"
        assert spread == "bear_call"

    def test_a_green_recent_bar_blocks_the_bear_call(self):
        bars = _falling_bars([(100.0, 101.0), (101.0, 100.5), (100.5, 99.0)])
        spread, signal, reason, _ = ema_vix._detect_signal(bars, rr_gate=True)
        assert spread is None
        assert signal == "EMA-Dn-no-RR"

    def test_the_in_progress_bar_is_not_counted(self):
        """The newest bar's period has not closed, so it cannot confirm anything."""
        # Two completed red bars, plus an in-progress green one.
        bars = _falling_bars([(100.0, 99.0), (99.0, 98.0), (98.0, 120.0)])
        _, signal, _, _ = ema_vix._detect_signal(bars, rr_gate=True)
        assert signal == "EMA-Dn+RR"

    def test_morning_bars_no_longer_decide_it(self):
        """9:30 and 10:00 green, but the recent bars are red -> confirmed."""
        now = datetime.now(NY).replace(hour=15, minute=0, second=0, microsecond=0)
        bars = _falling_bars([(100.0, 99.0), (99.0, 98.0), (98.0, 97.0)], now=now)
        morning = now.replace(hour=9, minute=30).astimezone(UTC)
        bars.insert(0, {"dt": morning, "open": 100.0, "close": 110.0})  # green 9:30
        bars.insert(1, {"dt": morning + BAR, "open": 110.0, "close": 120.0})  # green 10:00
        bars.sort(key=lambda b: b["dt"])
        _, signal, _, _ = ema_vix._detect_signal(bars, rr_gate=True)
        assert signal == "EMA-Dn+RR"

    def test_too_few_completed_bars_today_is_reported(self):
        """Early in the session there is nothing closed yet to confirm with."""
        now = datetime.now(NY)
        # History lands wholly on earlier days; today holds one in-progress bar.
        history = []
        start = (now - timedelta(days=4)).astimezone(UTC)
        for i in range(60):
            price = 100.0 + i if i < 30 else 100.0 + (60 - i) * 2
            history.append({"dt": start + BAR * i, "open": price, "close": price - 0.5})
        history = [b for b in history if b["dt"].astimezone(NY).date() < now.date()]
        history.append({"dt": now.astimezone(UTC), "open": 100.0, "close": 99.0})

        spread, signal, reason, _ = ema_vix._detect_signal(history, rr_gate=True)
        assert spread is None
        assert signal == "missing-bars-rr"
        assert "two closed bars" in reason

    def test_rr_gate_off_is_unaffected(self):
        bars = _falling_bars([(100.0, 101.0), (101.0, 102.0), (102.0, 103.0)])
        spread, signal, _, _ = ema_vix._detect_signal(bars, rr_gate=False)
        assert spread == "bear_call"
        assert signal == "EMA-Dn"

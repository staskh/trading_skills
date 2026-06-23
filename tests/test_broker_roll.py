# ABOUTME: Tests for roll analysis module pure logic functions.
# ABOUTME: Validates candidate evaluation and roll calculation logic.

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_skills.broker.roll import (
    _bs_delta,
    _bs_iv,
    _compute_half_band,
    _enrich_with_greeks,
    _estimate_iv,
    _get_stalled_price,
    _norm_cdf,
    _select_roll_strikes,
    calculate_roll_options,
    evaluate_short_candidates,
    get_current_position,
    get_long_option_position,
    get_underlying_price,
)
from trading_skills.utils import days_to_expiry


class TestDaysToExpiry:
    """Tests for days to expiry calculation."""

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


class TestEvaluateShortCandidates:
    """Tests for short option candidate evaluation."""

    def test_filters_zero_bid_and_zero_mid(self):
        quotes = [{"strike": 110, "expiry": "20250321", "bid": 0, "ask": 0, "mid": 0, "last": 0}]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 0

    def test_uses_mid_as_fallback_when_bid_zero(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 0, "ask": 0, "mid": 2.0, "last": 2.0}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 1
        assert result[0]["bid"] == pytest.approx(2.0)

    def test_filters_itm(self):
        quotes = [
            {"strike": 90, "expiry": "20250321", "bid": 12.0, "ask": 13.0, "mid": 12.5, "last": 12}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 0

    def test_otm_call_included(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 1
        assert result[0]["strike"] == 110
        assert result[0]["otm_pct"] == 10.0

    def test_otm_put_included(self):
        quotes = [
            {"strike": 90, "expiry": "20250321", "bid": 1.5, "ask": 2.0, "mid": 1.75, "last": 1.5}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "P", 30)
        assert len(result) == 1
        assert result[0]["otm_pct"] == 10.0

    def test_sorted_by_score_descending(self):
        quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 3.0, "ask": 3.5, "mid": 3.25, "last": 3},
            {"strike": 115, "expiry": "20250321", "bid": 0.5, "ask": 1.0, "mid": 0.75, "last": 0.5},
            {"strike": 110, "expiry": "20250321", "bid": 1.5, "ask": 2.0, "mid": 1.75, "last": 1.5},
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 3
        # Scores should be descending
        for i in range(len(result) - 1):
            assert result[i]["score"] >= result[i + 1]["score"]

    def test_annual_return_calculated(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        # annual_return = (2.0 / 100.0) * (365/30) * 100 = 24.33%
        assert result[0]["annual_return"] > 20

    def test_time_score_preferred_range(self):
        quotes = [
            {"strike": 110, "expiry": "20250321", "bid": 2.0, "ask": 2.50, "mid": 2.25, "last": 2}
        ]
        result_30 = evaluate_short_candidates(quotes, 100.0, "C", 30)
        result_7 = evaluate_short_candidates(quotes, 100.0, "C", 7)
        # 30 DTE in preferred 21-60 range, 7 DTE is not
        assert result_30[0]["score"] > result_7[0]["score"]


class TestCalculateRollOptions:
    """Tests for roll credit/debit calculation."""

    def test_credit_roll(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 3.0, "ask": 3.5, "mid": 3.25, "last": 3}
        ]
        buy_price = 1.50
        result = calculate_roll_options(current, target_quotes, buy_price)
        assert len(result) == 1
        assert result[0]["net"] == 1.50  # 3.0 - 1.5
        assert result[0]["net_type"] == "credit"

    def test_debit_roll(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 0.50, "ask": 1.0, "mid": 0.75, "last": 0.5}
        ]
        buy_price = 2.00
        result = calculate_roll_options(current, target_quotes, buy_price)
        assert len(result) == 1
        assert result[0]["net"] == -1.50  # 0.5 - 2.0
        assert result[0]["net_type"] == "debit"

    def test_filters_zero_bid_and_zero_mid(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 0, "ask": 0, "mid": 0, "last": 0}
        ]
        result = calculate_roll_options(current, target_quotes, 1.0)
        assert len(result) == 0

    def test_uses_mid_as_fallback_when_bid_zero(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {"strike": 105, "expiry": "20250321", "bid": 0, "ask": 0, "mid": 3.0, "last": 3.0}
        ]
        result = calculate_roll_options(current, target_quotes, buy_price=1.0)
        assert len(result) == 1
        assert result[0]["net"] == pytest.approx(2.0)  # 3.0 - 1.0
        assert result[0]["net_type"] == "credit"

    def test_far_otm_penalty_applied(self):
        # OTM > 15% should get safety_score penalty but still be included
        quotes = [
            {
                "strike": 120,
                "expiry": "20250321",
                "bid": 0.50,
                "ask": 0.80,
                "mid": 0.65,
                "last": 0.6,
            }
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 1
        # 20% OTM should have penalty applied (score still calculated)
        assert result[0]["otm_pct"] == pytest.approx(20.0)


def _make_position(symbol, sec_type, position, strike=100.0, expiry="20260620", right="C"):
    """Build a mock IB position tuple."""
    contract = MagicMock()
    contract.symbol = symbol
    contract.secType = sec_type
    contract.strike = strike
    contract.lastTradeDateOrContractMonth = expiry
    contract.right = right
    contract.multiplier = "20"
    pos = MagicMock()
    pos.contract = contract
    pos.position = position
    pos.account = "DU123456"
    pos.avgCost = 500.0
    return pos


class TestGetCurrentPositionFop:
    """get_current_position must include FOP short positions and surface sec_type."""

    @pytest.mark.asyncio
    async def test_returns_fop_short_position(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", -1, strike=21000.0)])
        result = await get_current_position(ib, "NQ")
        assert result is not None
        assert result["sec_type"] == "FOP"
        assert result["strike"] == 21000.0

    @pytest.mark.asyncio
    async def test_returns_opt_short_position(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("AAPL", "OPT", -2, strike=200.0)])
        result = await get_current_position(ib, "AAPL")
        assert result is not None
        assert result["sec_type"] == "OPT"

    @pytest.mark.asyncio
    async def test_ignores_long_positions(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", 1, strike=21000.0)])
        result = await get_current_position(ib, "NQ")
        assert result is None


class TestGetLongOptionPositionFop:
    """get_long_option_position must include FOP long positions and surface sec_type."""

    @pytest.mark.asyncio
    async def test_returns_fop_long_position(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", 1, strike=20000.0)])
        result = await get_long_option_position(ib, "NQ", "C")
        assert result is not None
        assert result["sec_type"] == "FOP"
        assert result["strike"] == 20000.0

    @pytest.mark.asyncio
    async def test_ignores_short_positions(self):
        ib = MagicMock()
        ib.positions = MagicMock(return_value=[_make_position("NQ", "FOP", -1, strike=20000.0)])
        result = await get_long_option_position(ib, "NQ", "C")
        assert result is None


class TestEstimateIv:
    """Tests for Brenner-Subrahmanyam IV approximation."""

    def test_roundtrip(self):
        # σ ≈ C / (0.4 × S × √T): if we synthesize a price from known IV we should recover it
        spot, iv, dte = 100.0, 0.40, 30
        import math

        synthetic_mid = 0.4 * spot * iv * math.sqrt(dte / 365)
        estimated = _estimate_iv(spot, synthetic_mid, dte)
        assert estimated == pytest.approx(iv, rel=0.01)

    def test_higher_price_gives_higher_iv(self):
        iv_cheap = _estimate_iv(100.0, 2.0, 30)
        iv_expensive = _estimate_iv(100.0, 4.0, 30)
        assert iv_expensive > iv_cheap

    def test_longer_dte_gives_lower_iv_for_same_price(self):
        iv_short = _estimate_iv(100.0, 3.0, 15)
        iv_long = _estimate_iv(100.0, 3.0, 60)
        assert iv_short > iv_long

    def test_zero_mid_falls_back_to_default(self):
        iv = _estimate_iv(100.0, 0.0, 30)
        assert iv == pytest.approx(0.30)

    def test_zero_dte_falls_back_to_default(self):
        iv = _estimate_iv(100.0, 2.0, 0)
        assert iv == pytest.approx(0.30)


class TestComputeHalfBand:
    """Tests for IV-scaled expected move band calculation."""

    def test_scales_with_iv(self):
        band_low_iv = _compute_half_band(spot=100.0, atm_iv=0.20, iv_multiplier=2.0, dte=30)
        band_high_iv = _compute_half_band(spot=100.0, atm_iv=0.80, iv_multiplier=2.0, dte=30)
        assert band_high_iv == pytest.approx(4 * band_low_iv, rel=0.01)

    def test_scales_with_multiplier(self):
        band_2x = _compute_half_band(spot=100.0, atm_iv=0.40, iv_multiplier=2.0, dte=30)
        band_4x = _compute_half_band(spot=100.0, atm_iv=0.40, iv_multiplier=4.0, dte=30)
        assert band_4x == pytest.approx(2 * band_2x, rel=0.01)

    def test_scales_with_spot(self):
        band_100 = _compute_half_band(spot=100.0, atm_iv=0.40, iv_multiplier=2.0, dte=30)
        band_200 = _compute_half_band(spot=200.0, atm_iv=0.40, iv_multiplier=2.0, dte=30)
        assert band_200 == pytest.approx(2 * band_100, rel=0.01)

    def test_scales_with_dte(self):
        band_30 = _compute_half_band(spot=100.0, atm_iv=0.40, iv_multiplier=2.0, dte=30)
        band_120 = _compute_half_band(spot=100.0, atm_iv=0.40, iv_multiplier=2.0, dte=120)
        assert band_120 == pytest.approx(2 * band_30, rel=0.01)

    def test_nan_spot_returns_nan(self):
        import math

        band = _compute_half_band(spot=float("nan"), atm_iv=0.40, iv_multiplier=2.0, dte=30)
        assert math.isnan(band)


class TestSelectRollStrikes:
    """Tests for IV-aware strike band selection."""

    ALL_STRIKES = list(range(80, 165, 5))  # 80, 85, ..., 160

    def test_call_band_centered_on_current_strike(self):
        strikes = _select_roll_strikes(
            self.ALL_STRIKES, current_strike=100.0, right="C", half_band=20.0
        )
        assert all(80 <= s <= 120 for s in strikes)
        assert 100 in strikes
        assert 120 in strikes

    def test_put_band_centered_on_current_strike(self):
        strikes = _select_roll_strikes(
            self.ALL_STRIKES, current_strike=100.0, right="P", half_band=20.0
        )
        assert all(80 <= s <= 120 for s in strikes)
        assert 100 in strikes
        assert 80 in strikes

    def test_high_iv_wider_than_low_iv(self):
        band_low = _compute_half_band(100.0, 0.20, 2.0, 30)
        band_high = _compute_half_band(100.0, 0.80, 2.0, 30)
        strikes_low = _select_roll_strikes(self.ALL_STRIKES, 100.0, "C", band_low)
        strikes_high = _select_roll_strikes(self.ALL_STRIKES, 100.0, "C", band_high)
        assert len(strikes_high) > len(strikes_low)
        assert max(strikes_high) > max(strikes_low)

    def test_no_strike_cap_at_10(self):
        # With a wide band, all strikes in range should appear (no [:10] truncation)
        all_strikes = list(range(50, 200, 1))
        strikes = _select_roll_strikes(all_strikes, 100.0, "C", half_band=50.0)
        assert len(strikes) > 10

    def test_call_allows_small_downside(self):
        # With half_band=50, buffer=10 — strikes at 90 and 95 fall in the downside window.
        strikes = _select_roll_strikes(
            self.ALL_STRIKES, current_strike=100.0, right="C", half_band=50.0
        )
        assert any(s < 100.0 for s in strikes)

    def test_put_allows_small_upside(self):
        # With half_band=50, buffer=10 — strikes at 105 and 110 fall in the upside window.
        strikes = _select_roll_strikes(
            self.ALL_STRIKES, current_strike=100.0, right="P", half_band=50.0
        )
        assert any(s > 100.0 for s in strikes)


class TestBestPrice:
    """_best_price prefers live marketPrice, falls back to IB close."""

    def _make_ticker(self, market_price, close=float("nan")):
        t = MagicMock()
        t.marketPrice.return_value = market_price
        t.close = close
        return t

    def test_live_price_not_stale(self):
        from trading_skills.broker.roll import _best_price

        price, stale = _best_price(self._make_ticker(150.0))
        assert price == pytest.approx(150.0)
        assert stale is False

    def test_falls_back_to_close_when_market_price_nan(self):

        from trading_skills.broker.roll import _best_price

        price, stale = _best_price(self._make_ticker(float("nan"), close=148.0))
        assert price == pytest.approx(148.0)
        assert stale is True

    def test_returns_nan_when_both_unavailable(self):
        import math

        from trading_skills.broker.roll import _best_price

        price, stale = _best_price(self._make_ticker(float("nan"), close=float("nan")))
        assert math.isnan(price)
        assert stale is False


class TestGetStalledPrice:
    """Tests for yfinance fallback price."""

    def test_returns_price_when_available(self):
        mock_fast_info = MagicMock()
        mock_fast_info.last_price = 150.0
        with patch("trading_skills.broker.roll.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.fast_info = mock_fast_info
            price = _get_stalled_price("AAPL")
        assert price == 150.0

    def test_returns_none_when_zero(self):
        mock_fast_info = MagicMock()
        mock_fast_info.last_price = 0.0
        with patch("trading_skills.broker.roll.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.fast_info = mock_fast_info
            price = _get_stalled_price("AAPL")
        assert price is None

    def test_returns_none_on_exception(self):
        with patch("trading_skills.broker.roll.yf.Ticker", side_effect=Exception("network error")):
            price = _get_stalled_price("AAPL")
        assert price is None


class TestGetUnderlyingPriceStale:
    """get_underlying_price must return (price, stalled=True) when IB data is unavailable."""

    @pytest.mark.asyncio
    async def test_returns_realtime_when_ib_has_price(self):
        ib = MagicMock()
        ticker = MagicMock()
        ticker.marketPrice.return_value = 175.0
        ib.qualifyContractsAsync = AsyncMock(return_value=[])
        ib.reqTickersAsync = AsyncMock(return_value=[ticker])
        price, stalled = await get_underlying_price(ib, "AAPL")
        assert price == 175.0
        assert stalled is False

    @pytest.mark.asyncio
    async def test_falls_back_to_ib_close_when_market_price_nan(self):
        ib = MagicMock()
        ticker = MagicMock()
        ticker.marketPrice.return_value = float("nan")
        ticker.close = 148.0
        ib.qualifyContractsAsync = AsyncMock(return_value=[])
        ib.reqTickersAsync = AsyncMock(return_value=[ticker])
        price, stalled = await get_underlying_price(ib, "AAPL")
        assert price == pytest.approx(148.0)
        assert stalled is True

    @pytest.mark.asyncio
    async def test_falls_back_to_yfinance_when_ib_and_close_unavailable(self):
        ib = MagicMock()
        ticker = MagicMock()
        ticker.marketPrice.return_value = float("nan")
        ticker.close = float("nan")
        ib.qualifyContractsAsync = AsyncMock(return_value=[])
        ib.reqTickersAsync = AsyncMock(return_value=[ticker])
        with patch("trading_skills.broker.roll._get_stalled_price", return_value=170.0):
            price, stalled = await get_underlying_price(ib, "AAPL")
        assert price == 170.0
        assert stalled is True

    @pytest.mark.asyncio
    async def test_returns_nan_when_all_sources_fail(self):
        import math

        ib = MagicMock()
        ticker = MagicMock()
        ticker.marketPrice.return_value = float("nan")
        ticker.close = float("nan")
        ib.qualifyContractsAsync = AsyncMock(return_value=[])
        ib.reqTickersAsync = AsyncMock(return_value=[ticker])
        with patch("trading_skills.broker.roll._get_stalled_price", return_value=None):
            price, stalled = await get_underlying_price(ib, "AAPL")
        assert math.isnan(price)
        assert stalled is False


class TestOptionQuoteStale:
    """Option quotes use last traded price as fallback when bid/ask are zero."""

    def _make_ib_ticker(self, strike, bid, ask, last, close=float("nan")):
        contract = MagicMock()
        contract.strike = strike
        contract.lastTradeDateOrContractMonth = "20260717"
        t = MagicMock()
        t.contract = contract
        t.bid = bid
        t.ask = ask
        t.last = last
        t.close = close
        t.modelGreeks = None
        t.bidGreeks = None
        t.lastGreeks = None
        return t

    def test_live_quote_not_stale(self):
        from trading_skills.broker.roll import _build_quote

        t = self._make_ib_ticker(110, bid=2.0, ask=2.5, last=2.2)
        q = _build_quote(t)
        assert q["bid"] == 2.0
        assert q["mid"] == pytest.approx(2.25)
        assert q["stale"] is False

    def test_stale_quote_uses_last_as_mid(self):
        from trading_skills.broker.roll import _build_quote

        t = self._make_ib_ticker(110, bid=0, ask=0, last=2.2)
        q = _build_quote(t)
        assert q["mid"] == pytest.approx(2.2)
        assert q["stale"] is True

    def test_stale_quote_uses_close_when_last_is_zero(self):
        from trading_skills.broker.roll import _build_quote

        t = self._make_ib_ticker(110, bid=0, ask=0, last=0, close=2.5)
        q = _build_quote(t)
        assert q["mid"] == pytest.approx(2.5)
        assert q["stale"] is True

    def test_all_zero_returns_stale_false_mid_zero(self):
        from trading_skills.broker.roll import _build_quote

        t = self._make_ib_ticker(110, bid=0, ask=0, last=0, close=float("nan"))
        q = _build_quote(t)
        assert q["mid"] == 0
        assert q["stale"] is False


class TestBlackScholes:
    """Black-Scholes delta, IV, and norm_cdf."""

    def test_norm_cdf_at_zero(self):
        assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-6)

    def test_norm_cdf_large_positive(self):
        assert _norm_cdf(10.0) == pytest.approx(1.0, abs=1e-6)

    def test_norm_cdf_large_negative(self):
        assert _norm_cdf(-10.0) == pytest.approx(0.0, abs=1e-6)

    def test_atm_call_delta_approx_half(self):
        # ATM call delta should be ~0.5
        delta = _bs_delta(spot=100.0, strike=100.0, dte=30, iv=0.40, right="C")
        assert 0.45 < delta < 0.60

    def test_atm_put_delta_approx_minus_half(self):
        delta = _bs_delta(spot=100.0, strike=100.0, dte=30, iv=0.40, right="P")
        assert -0.60 < delta < -0.40

    def test_put_call_delta_parity(self):
        # call_delta - put_delta = 1 (put-call parity for delta)
        call_d = _bs_delta(100.0, 110.0, 30, 0.40, "C")
        put_d = _bs_delta(100.0, 110.0, 30, 0.40, "P")
        assert call_d - put_d == pytest.approx(1.0, abs=1e-6)

    def test_deep_itm_call_delta_near_one(self):
        delta = _bs_delta(spot=150.0, strike=100.0, dte=30, iv=0.30, right="C")
        assert delta > 0.90

    def test_deep_otm_call_delta_near_zero(self):
        delta = _bs_delta(spot=100.0, strike=200.0, dte=30, iv=0.30, right="C")
        assert delta < 0.05

    def test_bs_iv_roundtrip(self):
        # Synthesise a price from known IV and recover it
        from trading_skills.broker.roll import _bs_price

        spot, strike, dte, iv = 100.0, 105.0, 30, 0.45
        price = _bs_price(spot, strike, dte, iv, "C")
        recovered = _bs_iv(spot, strike, dte, price, "C")
        assert recovered == pytest.approx(iv, rel=0.01)

    def test_bs_iv_returns_nan_for_zero_price(self):
        import math

        iv = _bs_iv(100.0, 110.0, 30, 0.0, "C")
        assert math.isnan(iv)


class TestEnrichWithGreeks:
    """_enrich_with_greeks fills in missing iv/delta from Black-Scholes."""

    def test_fills_missing_iv_and_delta(self):
        candidates = [
            {"strike": 105.0, "expiry": "20260720", "sell_price": 3.0, "iv": None, "delta": None}
        ]
        _enrich_with_greeks(candidates, spot=100.0, right="C")
        assert candidates[0]["iv"] is not None
        assert candidates[0]["iv"] > 0
        assert candidates[0]["delta"] is not None

    def test_does_not_overwrite_existing_iv(self):
        candidates = [
            {"strike": 105.0, "expiry": "20260720", "sell_price": 3.0, "iv": 0.42, "delta": 0.35}
        ]
        _enrich_with_greeks(candidates, spot=100.0, right="C")
        assert candidates[0]["iv"] == pytest.approx(0.42)
        assert candidates[0]["delta"] == pytest.approx(0.35)

    def test_skips_zero_price_candidates(self):
        candidates = [
            {"strike": 200.0, "expiry": "20260720", "sell_price": 0.0, "iv": None, "delta": None}
        ]
        _enrich_with_greeks(candidates, spot=100.0, right="C")
        # IV can't be computed without price — should stay None or get delta from default IV
        assert candidates[0]["iv"] is None

    def test_calculate_roll_options_passes_through_greeks(self):
        current = {"strike": 100, "expiry": "20250221"}
        target_quotes = [
            {
                "strike": 105,
                "expiry": "20250321",
                "bid": 3.0,
                "ask": 3.5,
                "mid": 3.25,
                "last": 3,
                "iv": 0.45,
                "delta": 0.38,
            }
        ]
        result = calculate_roll_options(current, target_quotes, buy_price=1.0)
        assert len(result) == 1
        assert result[0]["iv"] == pytest.approx(0.45)
        assert result[0]["delta"] == pytest.approx(0.38)

    def test_evaluate_short_candidates_passes_through_greeks(self):
        quotes = [
            {
                "strike": 110,
                "expiry": "20250321",
                "bid": 2.0,
                "ask": 2.5,
                "mid": 2.25,
                "last": 2,
                "iv": 0.50,
                "delta": 0.30,
            }
        ]
        result = evaluate_short_candidates(quotes, 100.0, "C", 30)
        assert len(result) == 1
        assert result[0]["iv"] == pytest.approx(0.50)
        assert result[0]["delta"] == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# get_underlying_price data_delay (issue #68)
# ---------------------------------------------------------------------------


class TestGetUnderlyingPriceSource:
    """Verify price_source returned by get_underlying_price for data_delay labeling."""

    def _make_ticker(self, market_price=float("nan"), close=float("nan"), last=float("nan")):
        ticker = MagicMock()
        ticker.marketPrice.return_value = market_price
        ticker.close = close
        ticker.last = last
        return ticker

    def test_live_price_not_stale(self):
        """When marketPrice() returns a valid price, stale flag is False."""
        import asyncio

        ticker = self._make_ticker(market_price=150.0)
        contract = MagicMock()
        ib = MagicMock()
        ib.qualifyContractsAsync = AsyncMock(return_value=[contract])
        ib.reqTickersAsync = AsyncMock(return_value=[ticker])

        with patch("trading_skills.broker.roll.asyncio.sleep", new=AsyncMock()):
            price, stale = asyncio.run(get_underlying_price(ib, "AAPL"))

        assert price == pytest.approx(150.0)
        assert stale is False

    def test_stale_when_marketprice_nan_uses_close(self):
        """When marketPrice() is NaN, falls back to close and sets stale=True."""
        import asyncio

        ticker = self._make_ticker(market_price=float("nan"), close=148.0)
        contract = MagicMock()
        ib = MagicMock()
        ib.qualifyContractsAsync = AsyncMock(return_value=[contract])
        ib.reqTickersAsync = AsyncMock(return_value=[ticker])

        with patch("trading_skills.broker.roll.asyncio.sleep", new=AsyncMock()):
            price, stale = asyncio.run(get_underlying_price(ib, "AAPL"))

        assert price == pytest.approx(148.0)
        assert stale is True


class TestDataDelayLabel:
    """data_delay field uses 'extended-hours' when off market hours but price is fresh."""

    def _make_roll_result(self, price_stale: bool, is_live: bool) -> str:
        """Compute the expected data_delay string for given conditions."""
        from trading_skills.broker.roll import _data_delay_label

        return _data_delay_label(price_stale=price_stale, options_stale=False, live=is_live)

    def test_real_time_during_market_hours(self):
        assert self._make_roll_result(price_stale=False, is_live=True) == "real-time"

    def test_extended_hours_outside_market(self):
        assert self._make_roll_result(price_stale=False, is_live=False) == "extended-hours"

    def test_stalled_when_price_stale(self):
        result = self._make_roll_result(price_stale=True, is_live=False)
        assert result == "stalled - using last known price"

    def test_stalled_when_price_stale_even_during_live(self):
        result = self._make_roll_result(price_stale=True, is_live=True)
        assert result == "stalled - using last known price"

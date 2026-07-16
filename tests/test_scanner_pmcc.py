# ABOUTME: Tests for PMCC scanner module using real Yahoo Finance data.
# ABOUTME: Validates PMCC scoring, option chain analysis, and constraints.


from datetime import date, datetime, timedelta

import pandas as pd

import trading_skills.scanner_pmcc as spm
from trading_skills.black_scholes import black_scholes_price
from trading_skills.scanner_pmcc import (
    analyze_pmcc,
    compute_atm_iv,
    compute_base_score,
    compute_earnings_score,
    compute_strike_density_score,
    compute_trend_score,
    compute_weekly_options_score,
    find_strike_by_delta,
    format_scan_markdown,
    format_scan_results,
    has_weekly_options,
)


class TestAnalyzePMCC:
    """Tests for PMCC analysis with real data."""

    def test_valid_symbol(self):
        result = analyze_pmcc("AAPL")
        assert result is not None
        assert result["symbol"] == "AAPL"
        # Should have either data or error
        assert "pmcc_score" in result or "error" in result

    def test_has_leaps_data(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert "leaps" in result
            leaps = result["leaps"]
            for field in ["expiry", "strike", "delta", "iv", "last_price", "bid", "ask", "mid"]:
                assert field in leaps, f"Missing LEAPS field: {field}"

    def test_has_short_data(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert "short" in result
            short = result["short"]
            for field in ["expiry", "strike", "delta", "iv", "last_price", "bid", "ask", "mid"]:
                assert field in short, f"Missing short field: {field}"

    def test_has_metrics(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert "metrics" in result
            metrics = result["metrics"]
            for field in [
                "net_debit",
                "short_yield_pct",
                "annual_yield_est_pct",
                "capital_required",
            ]:
                assert field in metrics, f"Missing metrics field: {field}"

    def test_short_strike_above_leaps(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert result["short"]["strike"] > result["leaps"]["strike"]

    def test_delta_ranges(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert 0 <= result["leaps"]["delta"] <= 1
            assert 0 <= result["short"]["delta"] <= 1

    def test_score_range(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            # Base 0-11, trend -2..+2, earnings -2..+1, weekly -1..0, strike -2..0
            assert -7 <= result["pmcc_score"] <= 14

    def test_has_score_breakdown(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert "score_breakdown" in result
            breakdown = result["score_breakdown"]
            assert "trend" in breakdown
            assert "earnings" in breakdown

    def test_score_breakdown_shows_trend_adjustment(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            breakdown = result["score_breakdown"]
            assert "trend_delta" in breakdown
            assert isinstance(breakdown["trend_delta"], float | int)

    def test_score_breakdown_shows_earnings_adjustment(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            breakdown = result["score_breakdown"]
            assert "earnings_delta" in breakdown
            assert isinstance(breakdown["earnings_delta"], float | int)

    def test_score_breakdown_has_all_base_components(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            bd = result["score_breakdown"]
            for key in [
                "leaps_delta_delta",
                "leaps_delta",
                "short_delta_delta",
                "short_delta",
                "leaps_liquidity_delta",
                "leaps_liquidity",
                "short_liquidity_delta",
                "short_liquidity",
                "leaps_spread_delta",
                "leaps_spread",
                "short_spread_delta",
                "short_spread",
                "iv_delta",
                "iv",
                "yield_delta",
                "yield",
            ]:
                assert key in bd, f"Missing score_breakdown key: {key}"

    def test_has_max_possible_score(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert "max_possible_score" in result
            assert result["max_possible_score"] == 14

    def test_score_breakdown_deltas_sum_to_pmcc_score(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" not in result:
            return
        bd = result["score_breakdown"]
        total = sum(bd[k] for k in bd if k.endswith("_delta") and isinstance(bd[k], (int, float)))
        assert abs(round(total, 1) - result["pmcc_score"]) < 0.01

    def test_iv_positive(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert result["iv_pct"] > 0

    def test_capital_required(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            expected = result["leaps"]["mid"] * 100
            assert abs(result["metrics"]["capital_required"] - expected) < 1.0

    def test_net_debit(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            expected = result["leaps"]["mid"] - result["short"]["mid"]
            assert abs(result["metrics"]["net_debit"] - expected) < 0.02

    def test_max_profit_uses_bs_leaps_value(self):
        """Max profit should use BS-priced LEAPS at short expiry, not just intrinsic."""
        result = analyze_pmcc("AAPL")
        if "pmcc_score" not in result:
            return
        leaps = result["leaps"]
        short = result["short"]
        metrics = result["metrics"]

        # LEAPS still has significant time remaining at short expiry
        remaining_days = leaps["days"] - short["days"]
        assert remaining_days > 200  # LEAPS should have 200+ days left

        # BS-priced LEAPS at short expiry (stock at short strike) includes time value,
        # so max_profit must exceed the intrinsic-only estimate
        intrinsic_only = (short["strike"] - leaps["strike"]) + short["mid"] - leaps["mid"]
        assert metrics["max_profit"] > intrinsic_only

        # Verify max_profit matches BS calculation
        remaining_T = remaining_days / 365
        iv = result["iv_pct"] / 100
        leaps_value_at_short_expiry = black_scholes_price(
            S=short["strike"],
            K=leaps["strike"],
            T=remaining_T,
            r=0.05,
            sigma=iv,
            option_type="call",
        )
        expected_max_profit = leaps_value_at_short_expiry + short["mid"] - leaps["mid"]
        # iv_pct is rounded to 1 decimal, so allow tolerance for BS repricing error
        assert abs(metrics["max_profit"] - expected_max_profit) < 0.10

    def test_leaps_iv_is_positive(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert result["leaps"]["iv"] > 0

    def test_short_iv_is_positive(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert result["short"]["iv"] > 0

    def test_has_earnings_date(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert "earnings_date" in result

    def test_symbol_without_options(self):
        result = analyze_pmcc("BRK.A")
        # May return None or dict with error
        assert result is None or "error" in result


class TestComputeTrendScore:
    """Tests for trend scoring pure function."""

    def _bullish_raw(self, price=100.0):
        return {
            "rsi": 60.0,
            "sma50": 90.0,  # price above
            "macd_line": 1.0,
            "macd_signal": 0.5,  # macd above signal
        }

    def _bearish_raw(self, price=100.0):
        return {
            "rsi": 40.0,
            "sma50": 110.0,  # price below
            "macd_line": -0.5,
            "macd_signal": 0.0,  # macd below signal
        }

    def test_bullish_gives_positive_delta(self):
        delta, breakdown = compute_trend_score(100.0, self._bullish_raw())
        assert delta > 0

    def test_bearish_gives_negative_delta(self):
        delta, breakdown = compute_trend_score(100.0, self._bearish_raw())
        assert delta < 0

    def test_breakdown_has_sma50_key(self):
        _, breakdown = compute_trend_score(100.0, self._bullish_raw())
        assert "sma50" in breakdown

    def test_breakdown_has_rsi_key(self):
        _, breakdown = compute_trend_score(100.0, self._bullish_raw())
        assert "rsi" in breakdown

    def test_breakdown_has_macd_key(self):
        _, breakdown = compute_trend_score(100.0, self._bullish_raw())
        assert "macd" in breakdown

    def test_missing_indicators_handled(self):
        raw = {"rsi": None, "sma50": None, "macd_line": None, "macd_signal": None}
        delta, breakdown = compute_trend_score(100.0, raw)
        assert delta == 0.0

    def test_max_bullish_score(self):
        delta, _ = compute_trend_score(100.0, self._bullish_raw())
        assert delta == 2.0

    def test_max_bearish_score(self):
        delta, _ = compute_trend_score(100.0, self._bearish_raw())
        assert delta == -2.0


class TestComputeBaseScore:
    """Tests for base scoring pure function."""

    def _perfect(self):
        return dict(
            actual_leaps_delta=0.80,
            actual_short_delta=0.20,
            leaps_liquidity=200,
            short_liquidity=1000,
            leaps_spread_pct=3.0,
            short_spread_pct=5.0,
            avg_iv=0.35,
            annual_yield_est=60.0,
            leaps_delta_target=0.80,
            short_delta_target=0.20,
        )

    def test_perfect_inputs_score_11(self):
        score, _ = compute_base_score(**self._perfect())
        assert score == 11.0

    def test_breakdown_has_all_keys(self):
        _, bd = compute_base_score(**self._perfect())
        for key in [
            "leaps_delta_delta",
            "leaps_delta",
            "short_delta_delta",
            "short_delta",
            "leaps_liquidity_delta",
            "leaps_liquidity",
            "short_liquidity_delta",
            "short_liquidity",
            "leaps_spread_delta",
            "leaps_spread",
            "short_spread_delta",
            "short_spread",
            "iv_delta",
            "iv",
            "yield_delta",
            "yield",
        ]:
            assert key in bd, f"Missing key: {key}"

    def test_deltas_sum_to_score(self):
        score, bd = compute_base_score(**self._perfect())
        total = sum(bd[k] for k in bd if k.endswith("_delta") and isinstance(bd[k], (int, float)))
        assert abs(total - score) < 0.01

    def test_poor_leaps_delta_scores_lower(self):
        kwargs = self._perfect()
        kwargs["actual_leaps_delta"] = 0.50  # far from target
        score, _ = compute_base_score(**kwargs)
        assert score < 11.0

    def test_low_liquidity_scores_lower(self):
        kwargs = self._perfect()
        kwargs["leaps_liquidity"] = 5
        kwargs["short_liquidity"] = 10
        score, _ = compute_base_score(**kwargs)
        assert score < 11.0

    def test_high_iv_scores_lower(self):
        kwargs = self._perfect()
        kwargs["avg_iv"] = 0.80  # too high
        score, _ = compute_base_score(**kwargs)
        assert score < 11.0

    def test_breakdown_explanation_strings(self):
        _, bd = compute_base_score(**self._perfect())
        # Explanation strings should start with + or -
        for key in [
            "leaps_delta",
            "short_delta",
            "leaps_liquidity",
            "short_liquidity",
            "leaps_spread",
            "short_spread",
            "iv",
            "yield",
        ]:
            assert isinstance(bd[key], str), f"{key} should be a string"
            assert bd[key].startswith("+") or bd[key].startswith("0"), (
                f"{key} explanation should start with '+' or '0', got: {bd[key]}"
            )


class TestComputeEarningsScore:
    """Tests for earnings proximity scoring pure function."""

    def _future_date(self, days):
        return (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")

    def test_far_earnings_gives_bonus(self):
        delta, _ = compute_earnings_score(self._future_date(60), short_days=14)
        assert delta == 1.0

    def test_earnings_within_short_expiry_gives_penalty(self):
        delta, _ = compute_earnings_score(self._future_date(7), short_days=14)
        assert delta < 0

    def test_earnings_between_short_and_45d_gives_penalty(self):
        delta, _ = compute_earnings_score(self._future_date(35), short_days=14)
        assert delta < 0

    def test_no_earnings_date_gives_neutral(self):
        delta, breakdown = compute_earnings_score(None, short_days=14)
        assert delta == 0.0

    def test_past_earnings_gives_neutral(self):
        delta, _ = compute_earnings_score(self._future_date(-10), short_days=14)
        assert delta == 0.0

    def test_breakdown_has_earnings_key(self):
        _, breakdown = compute_earnings_score(self._future_date(60), short_days=14)
        assert "earnings" in breakdown

    def test_earnings_exactly_at_short_expiry_gives_penalty(self):
        delta, _ = compute_earnings_score(self._future_date(14), short_days=14)
        assert delta < 0


class TestFormatScanResults:
    """Tests for format_scan_results."""

    def test_sorts_by_score_descending(self):
        results = [
            {"symbol": "A", "pmcc_score": 3, "metrics": {"annual_yield_est_pct": 10}},
            {"symbol": "B", "pmcc_score": 7, "metrics": {"annual_yield_est_pct": 20}},
            {"symbol": "C", "pmcc_score": 5, "metrics": {"annual_yield_est_pct": 15}},
        ]
        output = format_scan_results(results)
        scores = [r["pmcc_score"] for r in output["results"]]
        assert scores == [7, 5, 3]

    def test_filters_errors(self):
        results = [
            {"symbol": "A", "pmcc_score": 5, "metrics": {"annual_yield_est_pct": 10}},
            {"symbol": "B", "error": "No options"},
        ]
        output = format_scan_results(results)
        assert output["count"] == 1
        assert len(output["errors"]) == 1
        assert output["errors"][0]["symbol"] == "B"

    def test_secondary_sort_by_yield(self):
        results = [
            {"symbol": "A", "pmcc_score": 5, "metrics": {"annual_yield_est_pct": 10}},
            {"symbol": "B", "pmcc_score": 5, "metrics": {"annual_yield_est_pct": 30}},
        ]
        output = format_scan_results(results)
        symbols = [r["symbol"] for r in output["results"]]
        assert symbols == ["B", "A"]

    def test_handles_missing_metrics(self):
        results = [
            {"symbol": "A", "pmcc_score": 5},
        ]
        output = format_scan_results(results)
        assert output["count"] == 1

    def test_includes_scan_date(self):
        output = format_scan_results([])
        assert "scan_date" in output

    def test_empty_results(self):
        output = format_scan_results([])
        assert output["count"] == 0
        assert output["results"] == []
        assert output["errors"] == []


def _make_chain(strikes, bids, asks, last_prices, ivs, last_trade="2026-05-16"):
    return pd.DataFrame(
        {
            "strike": strikes,
            "bid": bids,
            "ask": asks,
            "lastPrice": last_prices,
            "impliedVolatility": ivs,
            "volume": [0] * len(strikes),
            "openInterest": [100] * len(strikes),
            "lastTradeDate": [pd.Timestamp(last_trade)] * len(strikes),
        }
    )


class TestFindStrikeByDeltaOffHours:
    """find_strike_by_delta must use lastPrice when bid=ask=0 (off-hours)."""

    def test_finds_strike_when_only_last_price_available(self):
        chain = _make_chain(
            strikes=[80.0, 90.0, 100.0, 110.0, 120.0],
            bids=[0.0] * 5,
            asks=[0.0] * 5,
            last_prices=[22.0, 14.0, 7.0, 2.5, 0.5],
            ivs=[0.30] * 5,
        )
        strike, option = find_strike_by_delta(chain, 100.0, 0.80, 365, 0.30)
        assert option is not None, "Should find a strike using lastPrice as fallback"

    def test_returns_none_when_all_prices_zero(self):
        chain = _make_chain(
            strikes=[80.0, 90.0, 100.0, 110.0, 120.0],
            bids=[0.0] * 5,
            asks=[0.0] * 5,
            last_prices=[0.0] * 5,
            ivs=[0.30] * 5,
        )
        strike, option = find_strike_by_delta(chain, 100.0, 0.80, 365, 0.30)
        assert option is None

    def test_prefers_bid_ask_over_last_price(self):
        """When both are available, bid/ask mid should take precedence."""
        chain = _make_chain(
            strikes=[85.0, 90.0],
            bids=[14.0, 10.0],
            asks=[15.0, 11.0],
            last_prices=[5.0, 5.0],  # stale last price
            ivs=[0.30, 0.30],
        )
        strike, option = find_strike_by_delta(chain, 100.0, 0.80, 365, 0.30)
        assert option is not None
        # mid should be from bid/ask, not lastPrice
        assert option["effective_mid"] == (option["bid"] + option["ask"]) / 2

    def test_delta_computed_from_last_price_iv_not_avg_iv(self):
        """When bid=ask=0, delta must use IV derived from lastPrice, not the passed-in avg_iv.

        Setup: short-dated OTM call (10 days, strike 105 on stock at 100).
        lastPrice=1.50 implies ~30% IV, giving delta ~0.27.
        avg_iv=0.80 (wrong LEAPS-derived value) would give a very different delta.
        The test verifies the delta is close to the lastPrice-implied value.
        """
        from trading_skills.black_scholes import black_scholes_delta, implied_volatility

        spot, strike, last_price, expiry_days = 100.0, 105.0, 1.50, 10
        last_trade = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        chain = _make_chain(
            strikes=[strike],
            bids=[0.0],
            asks=[0.0],
            last_prices=[last_price],
            ivs=[0.001],  # bad yfinance data
            last_trade=last_trade,
        )

        wrong_avg_iv = 0.80
        _, option = find_strike_by_delta(chain, spot, 0.20, expiry_days, wrong_avg_iv)
        assert option is not None

        # Compute expected delta from lastPrice IV
        T_last = (expiry_days + 1) / 365  # +1 day because lastTradeDate is yesterday
        iv_from_last = implied_volatility(last_price, spot, strike, T_last, 0.05, "call")
        expected_delta = black_scholes_delta(
            spot, strike, expiry_days / 365, 0.05, iv_from_last, "call"
        )

        wrong_iv_delta = black_scholes_delta(
            spot, strike, expiry_days / 365, 0.05, wrong_avg_iv, "call"
        )
        assert abs(option["calculated_delta"] - expected_delta) < 0.02, (
            f"Delta {option['calculated_delta']:.3f} should be close to lastPrice-derived "
            f"{expected_delta:.3f}, not avg_iv-derived {wrong_iv_delta:.3f}"
        )


class TestNaNOptionData:
    """analyze_pmcc must handle NaN volume/OI without crashing."""

    def _make_mock_ticker(self):
        from datetime import date, timedelta
        from unittest.mock import MagicMock

        today = date.today()
        leaps_exp = (today + timedelta(days=300)).strftime("%Y-%m-%d")
        short_exp = (today + timedelta(days=10)).strftime("%Y-%m-%d")

        nan = float("nan")
        leaps_calls = pd.DataFrame(
            {
                "strike": [100.0, 110.0, 120.0, 130.0, 140.0],
                "bid": [50.0, 42.0, 35.0, 28.0, 20.0],
                "ask": [52.0, 44.0, 37.0, 30.0, 22.0],
                "lastPrice": [51.0, 43.0, 36.0, 29.0, 21.0],
                "impliedVolatility": [0.30] * 5,
                "volume": [nan] * 5,
                "openInterest": [nan] * 5,
                "lastTradeDate": [pd.Timestamp("2026-05-16")] * 5,
            }
        )
        short_calls = pd.DataFrame(
            {
                "strike": [120.0, 125.0, 130.0, 135.0, 140.0],
                "bid": [3.0, 1.5, 0.8, 0.4, 0.2],
                "ask": [3.5, 2.0, 1.2, 0.8, 0.5],
                "lastPrice": [3.2, 1.7, 1.0, 0.6, 0.3],
                "impliedVolatility": [0.30] * 5,
                "volume": [nan] * 5,
                "openInterest": [nan] * 5,
                "lastTradeDate": [pd.Timestamp("2026-05-16")] * 5,
            }
        )

        mock = MagicMock()
        mock.info = {"currentPrice": 150.0}
        mock.options = [leaps_exp, short_exp]

        chain_leaps = MagicMock()
        chain_leaps.calls = leaps_calls
        chain_short = MagicMock()
        chain_short.calls = short_calls

        def option_chain(exp):
            return chain_leaps if exp == leaps_exp else chain_short

        mock.option_chain = option_chain
        mock.history = MagicMock(
            return_value=pd.DataFrame(
                {"Close": [145.0] * 90, "Volume": [1_000_000] * 90},
                index=pd.date_range("2025-02-17", periods=90),
            )
        )
        return mock

    def test_nan_volume_oi_does_not_crash(self):
        result = analyze_pmcc("TEST", ticker=self._make_mock_ticker())
        assert result is not None
        assert "pmcc_score" in result, f"Expected valid result, got error: {result.get('error')}"
        assert result["leaps"]["volume"] == 0
        assert result["leaps"]["oi"] == 0
        assert result["short"]["volume"] == 0
        assert result["short"]["oi"] == 0

    def test_iv_and_last_price_present(self):
        result = analyze_pmcc("TEST", ticker=self._make_mock_ticker())
        assert result is not None
        assert "pmcc_score" in result
        assert "iv" in result["leaps"]
        assert "last_price" in result["leaps"]
        assert "iv" in result["short"]
        assert "last_price" in result["short"]
        assert result["leaps"]["iv"] > 0
        assert result["short"]["iv"] > 0


class TestComputeAtmIv:
    """compute_atm_iv always computes IV from market price data, never from Yahoo's column."""

    def test_returns_valid_iv_from_market_data(self):
        # Realistic bid/ask prices for ~30% IV on 1-year ATM options
        # (S=100, K=100, T≈1yr, r=5%, σ=30% → C≈14.2)
        calls = _make_chain(
            strikes=[95.0, 100.0, 105.0],
            bids=[16.3, 13.7, 11.5],
            asks=[17.3, 14.7, 12.5],
            last_prices=[16.8, 14.2, 12.0],
            ivs=[0.30, 0.28, 0.32],  # unused — computed from price
        )
        iv = compute_atm_iv(calls, 100.0, "2027-05-18")
        assert iv is not None
        assert 0.25 <= iv <= 0.40

    def test_always_computes_from_price_not_yahoo(self):
        """IV must be computed from bid/ask mid, never from Yahoo's impliedVolatility."""
        calls = _make_chain(
            strikes=[95.0, 100.0, 105.0],
            bids=[16.3, 13.7, 11.5],
            asks=[17.3, 14.7, 12.5],
            last_prices=[16.8, 14.2, 12.0],
            ivs=[0.001, 0.001, 0.001],  # bad Yahoo data — must be ignored
        )
        iv = compute_atm_iv(calls, 100.0, "2027-05-18")
        assert iv is not None
        # Should compute ~30% IV from bid/ask, not use the bad Yahoo 0.001
        assert 0.25 <= iv <= 0.40, f"Expected IV ~30% from price, got {iv:.3f}"

    def test_falls_back_to_last_price_when_no_bid_ask(self):
        """When bid=ask=0, compute IV from lastPrice using lastTradeDate."""
        calls = _make_chain(
            strikes=[95.0, 100.0, 105.0],
            bids=[0.0, 0.0, 0.0],
            asks=[0.0, 0.0, 0.0],
            last_prices=[8.0, 5.0, 2.5],
            ivs=[0.001, 0.001, 0.001],
            last_trade="2026-05-16",
        )
        iv = compute_atm_iv(calls, 100.0, "2027-05-18")
        assert iv is not None
        assert iv >= 0.01, f"Fallback IV should be meaningful, got {iv}"

    def test_returns_default_when_no_last_price_either(self):
        calls = _make_chain(
            strikes=[95.0, 100.0, 105.0],
            bids=[0.0, 0.0, 0.0],
            asks=[0.0, 0.0, 0.0],
            last_prices=[0.0, 0.0, 0.0],
            ivs=[0.001, 0.001, 0.001],
        )
        iv = compute_atm_iv(calls, 100.0, "2027-05-18")
        assert iv == 0.30  # default fallback


class TestFindStrikeByDeltaIV:
    """find_strike_by_delta must always compute IV from price, not Yahoo's column."""

    def test_calculated_iv_present_in_result(self):
        """Returned option dict must include calculated_iv."""
        chain = _make_chain(
            strikes=[85.0, 90.0, 95.0, 100.0],
            bids=[16.0, 13.0, 10.0, 7.0],
            asks=[17.0, 14.0, 11.0, 8.0],
            last_prices=[16.5, 13.5, 10.5, 7.5],
            ivs=[0.001] * 4,
        )
        _, option = find_strike_by_delta(chain, 100.0, 0.80, 365, 0.30)
        assert option is not None
        assert "calculated_iv" in option, "Option must include calculated_iv"
        assert option["calculated_iv"] > 0

    def test_iv_from_bid_ask_not_yahoo(self):
        """IV computed from bid/ask mid, ignoring Yahoo's impliedVolatility (0.001)."""
        # ATM call: S=K=100, T=1yr, bid/ask mid=14.2 → IV ≈ 30%
        chain = _make_chain(
            strikes=[100.0],
            bids=[13.7],
            asks=[14.7],
            last_prices=[14.2],
            ivs=[0.001],  # bad Yahoo data — must be ignored
        )
        _, option = find_strike_by_delta(chain, 100.0, 0.50, 365, 0.80)
        assert option is not None
        # With avg_iv=0.80 the delta would be ~0.85+; with true IV~30% it's ~0.54
        # So calculated_iv must be far from 0.80
        assert option["calculated_iv"] < 0.60, (
            f"IV {option['calculated_iv']:.3f} should be ~30%, not avg_iv 0.80"
        )

    def test_off_hours_calculated_iv_from_last_price(self):
        """When bid=ask=0, calculated_iv derived from lastPrice."""
        last_trade = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        chain = _make_chain(
            strikes=[100.0],
            bids=[0.0],
            asks=[0.0],
            last_prices=[14.2],
            ivs=[0.001],
            last_trade=last_trade,
        )
        _, option = find_strike_by_delta(chain, 100.0, 0.50, 365, 0.80)
        assert option is not None
        assert "calculated_iv" in option
        assert option["calculated_iv"] > 0.01


class TestFormatScanMarkdown:
    """format_scan_markdown renders scan output as structured markdown report."""

    def _make_scan_output(self):
        result = {
            "symbol": "AAPL",
            "price": 150.0,
            "iv_pct": 30.0,
            "pmcc_score": 10.0,
            "max_possible_score": 14,
            "earnings_date": "2026-08-01",
            "industry": "Consumer Electronics",
            "description": "Apple designs and sells consumer electronics.",
            "has_weeklies": True,
            "short_window": "7-21",
            "leaps": {
                "expiry": "2027-01-15",
                "days": 300,
                "strike": 120.0,
                "delta": 0.80,
                "iv": 0.30,
                "bid": 35.0,
                "ask": 36.0,
                "mid": 35.5,
                "last_price": 35.2,
                "spread_pct": 2.8,
                "volume": 100,
                "oi": 500,
            },
            "short": {
                "expiry": "2026-06-06",
                "days": 14,
                "strike": 155.0,
                "delta": 0.20,
                "iv": 0.28,
                "bid": 1.5,
                "ask": 1.8,
                "mid": 1.65,
                "last_price": 1.6,
                "spread_pct": 18.0,
                "volume": 200,
                "oi": 1000,
            },
            "metrics": {
                "net_debit": 33.85,
                "short_yield_pct": 4.6,
                "annual_yield_est_pct": 120.0,
                "capital_required": 3550.0,
                "max_profit": 5.0,
                "roi_pct": 14.1,
            },
            "score_breakdown": {
                "trend_delta": 1.5,
                "trend": {"sma50": "+1.0", "rsi": "+0.5"},
                "earnings_delta": 1.0,
                "earnings": {"earnings": "+1.0 (earnings 72d away)"},
                "leaps_delta_delta": 2.0,
                "leaps_delta": "+2.0",
                "short_delta_delta": 1.0,
                "short_delta": "+1.0",
                "leaps_liquidity_delta": 1.0,
                "leaps_liquidity": "+1.0",
                "short_liquidity_delta": 1.0,
                "short_liquidity": "+1.0",
                "leaps_spread_delta": 1.0,
                "leaps_spread": "+1.0",
                "short_spread_delta": 0.5,
                "short_spread": "+0.5",
                "iv_delta": 1.0,
                "iv": "+1.0",
                "yield_delta": 2.0,
                "yield": "+2.0",
                "weekly_options_delta": 0.0,
                "weekly_options": "0.0 (weekly options available)",
                "strike_density_delta": -1.0,
                "strike_density": "-1.0 (only 4 strikes between spot and short)",
            },
        }
        return {
            "results": [result],
            "scan_date": "2026-05-21 10:00 ET",
            "count": 1,
            "errors": [],
            "criteria": {},
        }

    def test_returns_string(self):
        md = format_scan_markdown(self._make_scan_output())
        assert isinstance(md, str)
        assert len(md) > 0

    def test_has_summary_table(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "| Symbol" in md
        assert "AAPL" in md

    def test_summary_table_has_required_columns(self):
        md = format_scan_markdown(self._make_scan_output())
        for col in ["Symbol", "Price", "IV%", "Capital", "Ann. Yield", "Trend", "PMCC Score"]:
            assert col in md, f"Summary table missing column: {col}"

    def test_has_per_symbol_leaps_section(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "LEAPS" in md

    def test_has_per_symbol_short_section(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "Short" in md or "short call" in md.lower()

    def test_summary_sorted_by_score(self):
        output = self._make_scan_output()
        output["results"].append(
            {
                **output["results"][0],
                "symbol": "MSFT",
                "pmcc_score": 12.0,
                "metrics": {**output["results"][0]["metrics"]},
            }
        )
        md = format_scan_markdown(output)
        aapl_pos = md.find("AAPL")
        msft_pos = md.find("MSFT")
        # MSFT (score 12) should appear before AAPL (score 10) in summary
        assert msft_pos < aapl_pos

    def test_empty_results(self):
        output = {
            "results": [],
            "scan_date": "2026-05-21 10:00 ET",
            "count": 0,
            "errors": [],
            "criteria": {},
        }
        md = format_scan_markdown(output)
        assert isinstance(md, str)

    def test_summary_has_industry_column(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "Industry" in md
        assert "Consumer Electronics" in md

    def test_detail_has_company_description(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "Apple designs and sells consumer electronics." in md

    def test_has_indicators_section(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "Indicators" in md
        assert "SMA50" in md

    def test_summary_has_weeklies_column(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "Weeklies" in md

    def test_strike_density_shown_as_weakness(self):
        md = format_scan_markdown(self._make_scan_output())
        assert "strikes between spot and short" in md


def _clean_calls(strikes, base_bid, step, volume=500, oi=1000, last_trade="2026-05-16"):
    """Build a valid calls DataFrame with descending bid/ask as strike rises."""
    n = len(strikes)
    bids = [max(0.1, base_bid - i * step) for i in range(n)]
    asks = [b + 0.5 for b in bids]
    last = [(b + a) / 2 for b, a in zip(bids, asks)]
    return pd.DataFrame(
        {
            "strike": strikes,
            "bid": bids,
            "ask": asks,
            "lastPrice": last,
            "impliedVolatility": [0.30] * n,
            "volume": [volume] * n,
            "openInterest": [oi] * n,
            "lastTradeDate": [pd.Timestamp(last_trade)] * n,
        }
    )


def _mock_ticker(day_offsets, price=150.0, info=None):
    """Build a mock yfinance Ticker with expirations at the given day offsets.

    The largest offset is treated as the LEAPS expiry; all others share a short chain.
    """
    from unittest.mock import MagicMock

    today = date.today()
    expirations = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in day_offsets]
    leaps_expiry = expirations[day_offsets.index(max(day_offsets))]

    leaps_calls = _clean_calls([100.0, 110.0, 120.0, 130.0, 140.0], base_bid=52.0, step=8.0)
    short_calls = _clean_calls([150.0, 155.0, 160.0, 165.0, 170.0, 175.0], base_bid=4.0, step=0.7)

    mock = MagicMock()
    mock.info = info or {"currentPrice": price}
    mock.options = expirations

    def option_chain(exp):
        chain = MagicMock()
        chain.calls = leaps_calls if exp == leaps_expiry else short_calls
        return chain

    mock.option_chain = option_chain
    mock.history = MagicMock(
        return_value=pd.DataFrame(
            {"Close": [145.0] * 90, "Volume": [1_000_000] * 90},
            index=pd.date_range("2025-02-17", periods=90),
        )
    )
    return mock


class TestEarningsScoreTimezone:
    """A1: date math must use America/New_York, not naive datetime.now()."""

    def test_uses_ny_date_not_naive(self, monkeypatch):
        real_datetime = datetime

        class FakeDatetime:
            @classmethod
            def now(cls, tz=None):
                # Simulate a UTC host already past midnight: naive now() is a day ahead
                if tz is None:
                    return real_datetime(2026, 1, 2, 4, 0, 0)
                return real_datetime(2026, 1, 1, 23, 0, 0, tzinfo=tz)

            @staticmethod
            def strptime(*args, **kwargs):
                return real_datetime.strptime(*args, **kwargs)

        monkeypatch.setattr(spm, "datetime", FakeDatetime)
        # Earnings on Feb 16: 46 days from NY date (Jan 1) -> +1.0 (>45),
        # but 45 days from naive Jan 2 -> -1.0. NY answer is correct.
        delta, _ = compute_earnings_score("2026-02-16", short_days=14)
        assert delta == 1.0


class TestShortYieldSemantics:
    """A3: short_yield_pct is the period yield; annual is that annualized by short_days."""

    def test_annual_is_period_yield_annualized(self, monkeypatch):
        monkeypatch.setattr(spm, "get_next_earnings_date", lambda s: None)
        result = analyze_pmcc("TEST", ticker=_mock_ticker([14, 300]))
        assert "pmcc_score" in result, result.get("error")
        m = result["metrics"]
        sd = result["short"]["days"]
        expected_annual = m["short_yield_pct"] * 365 / sd
        assert abs(m["annual_yield_est_pct"] - expected_annual) < 0.3


class TestShortWindowReported:
    """A4: analyze_pmcc reports the short-expiry window actually used."""

    def test_reports_primary_window(self, monkeypatch):
        monkeypatch.setattr(spm, "get_next_earnings_date", lambda s: None)
        result = analyze_pmcc("TEST", ticker=_mock_ticker([14, 300]))
        assert "pmcc_score" in result, result.get("error")
        assert result["short_window"] == "7-21"

    def test_reports_fallback_window(self, monkeypatch):
        monkeypatch.setattr(spm, "get_next_earnings_date", lambda s: None)
        # 25 days is outside 7-21 but inside the 5-30 fallback window
        result = analyze_pmcc("TEST", ticker=_mock_ticker([25, 300]))
        assert "pmcc_score" in result, result.get("error")
        assert result["short_window"] == "5-30 (fallback)"


class TestHasWeeklyOptions:
    """C1: weekly-options detection helper."""

    def test_detects_weeklies_from_close_expirations(self):
        today = date.today()
        exps = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in (7, 14, 21, 300)]
        assert has_weekly_options(exps, today) is True

    def test_no_weeklies_when_only_monthly(self):
        today = date.today()
        exps = [(today + timedelta(days=d)).strftime("%Y-%m-%d") for d in (18, 46, 300)]
        assert has_weekly_options(exps, today) is False

    def test_weekly_score_penalizes_absence(self):
        delta, bd = compute_weekly_options_score(False)
        assert delta == -1.0
        assert "weekly_options" in bd
        assert bd["weekly_options_delta"] == -1.0

    def test_weekly_score_neutral_when_present(self):
        delta, bd = compute_weekly_options_score(True)
        assert delta == 0.0
        assert bd["weekly_options_delta"] == 0.0

    def test_integration_no_weeklies_applies_penalty(self, monkeypatch):
        monkeypatch.setattr(spm, "get_next_earnings_date", lambda s: None)
        result = analyze_pmcc("TEST", ticker=_mock_ticker([14, 300]))
        assert "pmcc_score" in result, result.get("error")
        assert result["has_weeklies"] is False
        assert result["score_breakdown"]["weekly_options_delta"] == -1.0

    def test_integration_weeklies_no_penalty(self, monkeypatch):
        monkeypatch.setattr(spm, "get_next_earnings_date", lambda s: None)
        result = analyze_pmcc("TEST", ticker=_mock_ticker([7, 14, 21, 300]))
        assert "pmcc_score" in result, result.get("error")
        assert result["has_weeklies"] is True
        assert result["score_breakdown"]["weekly_options_delta"] == 0.0


class TestStrikeDensityScore:
    """C2: strike-density penalty between spot and short strike."""

    def test_fewer_than_three_strikes_penalized_two(self):
        delta, bd = compute_strike_density_score(2)
        assert delta == -2.0
        assert bd["strike_density_delta"] == -2.0

    def test_fewer_than_five_strikes_penalized_one(self):
        delta, bd = compute_strike_density_score(4)
        assert delta == -1.0

    def test_five_or_more_strikes_no_penalty(self):
        delta, bd = compute_strike_density_score(5)
        assert delta == 0.0

    def test_integration_breakdown_present(self, monkeypatch):
        monkeypatch.setattr(spm, "get_next_earnings_date", lambda s: None)
        result = analyze_pmcc("TEST", ticker=_mock_ticker([14, 300]))
        assert "pmcc_score" in result, result.get("error")
        bd = result["score_breakdown"]
        assert "strike_density_delta" in bd
        assert bd["strike_density_delta"] in (-2.0, -1.0, 0.0)

    def test_integration_deltas_still_sum(self, monkeypatch):
        monkeypatch.setattr(spm, "get_next_earnings_date", lambda s: None)
        result = analyze_pmcc("TEST", ticker=_mock_ticker([14, 300]))
        assert "pmcc_score" in result, result.get("error")
        bd = result["score_breakdown"]
        total = sum(bd[k] for k in bd if k.endswith("_delta") and isinstance(bd[k], (int, float)))
        assert abs(round(total, 1) - result["pmcc_score"]) < 0.01

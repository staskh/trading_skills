# ABOUTME: Tests for PMCC scanner module using real Yahoo Finance data.
# ABOUTME: Validates PMCC scoring, option chain analysis, and constraints.


from datetime import date, timedelta

from trading_skills.black_scholes import black_scholes_price
from trading_skills.scanner_pmcc import (
    analyze_pmcc,
    compute_base_score,
    compute_earnings_score,
    compute_trend_score,
    format_scan_results,
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
            for field in ["expiry", "strike", "delta", "bid", "ask", "mid"]:
                assert field in leaps, f"Missing LEAPS field: {field}"

    def test_has_short_data(self):
        result = analyze_pmcc("AAPL")
        if "pmcc_score" in result:
            assert "short" in result
            short = result["short"]
            for field in ["expiry", "strike", "delta", "bid", "ask", "mid"]:
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
            # Base score 0-11, trend adj -2 to +2, earnings adj -2 to +1
            assert -4 <= result["pmcc_score"] <= 14

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

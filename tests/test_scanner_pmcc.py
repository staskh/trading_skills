# ABOUTME: Tests for PMCC scanner module using real Yahoo Finance data.
# ABOUTME: Validates PMCC scoring, option chain analysis, and constraints.


from trading_skills.black_scholes import black_scholes_price
from trading_skills.scanner_pmcc import analyze_pmcc, format_scan_results


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
            assert 0 <= result["pmcc_score"] <= 12

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
            assert abs(result["metrics"]["net_debit"] - expected) < 0.01

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

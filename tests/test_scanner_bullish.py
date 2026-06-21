# ABOUTME: Tests for bullish scanner module using real Yahoo Finance data.
# ABOUTME: Validates scoring, signal generation, and multi-symbol scanning.


from trading_skills.scanner_bullish import (
    _score_dual_crossover,
    compute_bullish_score,
    scan_symbols,
)


class TestScoreDualCrossover:
    """Tests for dual crossover confirmation scoring — pure logic, no live data."""

    def _xover(self, direction, days_ago):
        return {"direction": direction, "days_ago": days_ago}

    # --- both up ---
    def test_both_up_fresh_gives_plus_one(self):
        score, signal = _score_dual_crossover(self._xover("up", 5), self._xover("up", 3))
        assert score == 1.0
        assert "bullish" in signal.lower()
        assert "fresh" in signal.lower()

    def test_both_up_stale_gives_plus_half(self):
        score, signal = _score_dual_crossover(self._xover("up", 20), self._xover("up", 15))
        assert score == 0.5
        assert "bullish" in signal.lower()
        assert "fresh" not in signal.lower()

    def test_both_up_boundary_10_days_is_fresh(self):
        score, _ = _score_dual_crossover(self._xover("up", 10), self._xover("up", 10))
        assert score == 1.0

    def test_both_up_boundary_11_days_is_stale(self):
        score, _ = _score_dual_crossover(self._xover("up", 11), self._xover("up", 10))
        assert score == 0.5

    # --- both down ---
    def test_both_down_fresh_gives_minus_one(self):
        score, signal = _score_dual_crossover(self._xover("down", 5), self._xover("down", 3))
        assert score == -1.0
        assert "bearish" in signal.lower()
        assert "fresh" in signal.lower()

    def test_both_down_stale_gives_minus_half(self):
        score, signal = _score_dual_crossover(self._xover("down", 20), self._xover("down", 15))
        assert score == -0.5
        assert "bearish" in signal.lower()

    # --- conflict ---
    def test_conflict_ema_up_macd_down(self):
        score, signal = _score_dual_crossover(self._xover("up", 3), self._xover("down", 5))
        assert score == -0.5
        assert "conflict" in signal.lower()

    def test_conflict_ema_down_macd_up(self):
        score, signal = _score_dual_crossover(self._xover("down", 3), self._xover("up", 5))
        assert score == -0.5
        assert "conflict" in signal.lower()

    # --- missing crossover ---
    def test_ema_none_returns_zero(self):
        score, signal = _score_dual_crossover(None, self._xover("up", 3))
        assert score == 0.0
        assert signal is None

    def test_macd_none_returns_zero(self):
        score, signal = _score_dual_crossover(self._xover("up", 3), None)
        assert score == 0.0
        assert signal is None

    def test_both_none_returns_zero(self):
        score, signal = _score_dual_crossover(None, None)
        assert score == 0.0
        assert signal is None


class TestComputeBullishScore:
    """Tests for single symbol bullish scoring."""

    def test_valid_symbol(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert result["symbol"] == "AAPL"
        assert "score" in result
        assert isinstance(result["score"], (int, float))

    def test_score_range(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert -2 <= result["score"] <= 10

    def test_has_indicators(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert "price" in result
        assert "rsi" in result
        assert "adx" in result
        assert "signals" in result

    def test_rsi_in_range(self):
        result = compute_bullish_score("AAPL")
        if result and result["rsi"] is not None:
            assert 0 <= result["rsi"] <= 100

    def test_has_earnings_info(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert "next_earnings" in result
        assert "earnings_timing" in result

    def test_signals_is_list(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert isinstance(result["signals"], list)

    def test_has_ema_fields(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert "ema9" in result
        assert "ema21" in result
        assert "ema_crossover" in result

    def test_ema_crossover_structure(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        xover = result["ema_crossover"]
        if xover is not None:
            assert xover["direction"] in ("up", "down")
            assert isinstance(xover["days_ago"], int)
            assert xover["days_ago"] >= 0

    def test_has_macd_crossover_field(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        assert "macd_crossover" in result

    def test_macd_crossover_structure(self):
        result = compute_bullish_score("AAPL")
        assert result is not None
        xover = result["macd_crossover"]
        if xover is not None:
            assert xover["direction"] in ("up", "down")
            assert isinstance(xover["days_ago"], int)
            assert xover["days_ago"] >= 0

    def test_invalid_symbol_returns_none(self):
        result = compute_bullish_score("INVALIDXYZ123")
        assert result is None


class TestScanSymbols:
    """Tests for multi-symbol scanning."""

    def test_scan_returns_sorted(self):
        results = scan_symbols(["AAPL", "MSFT", "NVDA"], top_n=3)
        assert len(results) > 0
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_limits(self):
        results = scan_symbols(["AAPL", "MSFT", "NVDA", "GOOGL"], top_n=2)
        assert len(results) <= 2

    def test_invalid_excluded(self):
        results = scan_symbols(["AAPL", "INVALIDXYZ123"], top_n=5)
        symbols = [r["symbol"] for r in results]
        assert "INVALIDXYZ123" not in symbols
        assert "AAPL" in symbols

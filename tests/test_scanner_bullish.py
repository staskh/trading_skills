# ABOUTME: Tests for bullish scanner module using real Yahoo Finance data.
# ABOUTME: Validates scoring, signal generation, and multi-symbol scanning.


from trading_skills.scanner_bullish import compute_bullish_score, scan_symbols


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

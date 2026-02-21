# ABOUTME: Tests for technical analysis module using real Yahoo Finance data.
# ABOUTME: Validates indicator computation, signal generation, and multi-symbol.


import numpy as np
import pandas as pd

from trading_skills.technicals import (
    compute_indicators,
    compute_multi_symbol,
    compute_raw_indicators,
    get_earnings_data,
)


class TestComputeIndicators:
    """Tests for single-symbol indicator computation."""

    def test_returns_structure(self):
        result = compute_indicators("AAPL", period="3mo")
        assert result["symbol"] == "AAPL"
        assert "indicators" in result
        assert "price" in result
        assert "signals" in result

    def test_rsi_indicator(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "rsi" in result["indicators"]
        rsi = result["indicators"]["rsi"]
        assert "value" in rsi
        assert 0 <= rsi["value"] <= 100

    def test_macd_indicator(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "macd" in result["indicators"]
        macd = result["indicators"]["macd"]
        assert "macd" in macd
        assert "signal" in macd
        assert "histogram" in macd

    def test_bollinger_bands(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "bollinger" in result["indicators"]
        bb = result["indicators"]["bollinger"]
        assert bb["lower"] < bb["middle"] < bb["upper"]

    def test_sma(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "sma" in result["indicators"]
        assert "sma20" in result["indicators"]["sma"]

    def test_ema(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "ema" in result["indicators"]
        assert "ema12" in result["indicators"]["ema"]

    def test_custom_indicators(self):
        result = compute_indicators("AAPL", period="3mo", indicators=["rsi", "macd"])
        assert "rsi" in result["indicators"]
        assert "macd" in result["indicators"]
        # Should NOT have bollinger since not requested
        assert "bollinger" not in result["indicators"]

    def test_risk_metrics_included(self):
        result = compute_indicators("AAPL", period="3mo")
        assert "risk_metrics" in result
        rm = result["risk_metrics"]
        assert "volatility_annualized_pct" in rm
        assert "sharpe_ratio" in rm

    def test_signals_is_list(self):
        result = compute_indicators("AAPL", period="3mo")
        assert isinstance(result["signals"], list)

    def test_invalid_symbol(self):
        result = compute_indicators("INVALIDXYZ123")
        assert "error" in result


class TestComputeMultiSymbol:
    """Tests for multi-symbol analysis."""

    def test_returns_results(self):
        result = compute_multi_symbol(["AAPL", "MSFT"], period="1mo")
        assert "results" in result
        assert len(result["results"]) == 2

    def test_each_symbol_present(self):
        result = compute_multi_symbol(["AAPL", "MSFT"], period="1mo", indicators=["rsi"])
        symbols = [r["symbol"] for r in result["results"]]
        assert "AAPL" in symbols
        assert "MSFT" in symbols


class TestGetEarningsData:
    """Tests for earnings data fetching."""

    def test_returns_symbol(self):
        result = get_earnings_data("AAPL")
        assert result["symbol"] == "AAPL"

    def test_has_history_or_upcoming(self):
        result = get_earnings_data("AAPL")
        # Should have at least some earnings data
        assert "history" in result or "upcoming" in result

    def test_history_entries(self):
        result = get_earnings_data("AAPL")
        if "history" in result:
            for entry in result["history"]:
                assert "date" in entry
                assert "estimated_eps" in entry or "reported_eps" in entry

    def test_invalid_symbol(self):
        result = get_earnings_data("INVALIDXYZ123")
        assert result["symbol"] == "INVALIDXYZ123"


class TestComputeRawIndicators:
    """Tests for raw indicator extraction from DataFrame."""

    def _make_df(self, n=100):
        """Create a synthetic OHLCV DataFrame with enough data for indicators."""
        np.random.seed(42)
        dates = pd.date_range(end="2025-06-01", periods=n, freq="D")
        close = 100 + np.cumsum(np.random.randn(n) * 0.5)
        return pd.DataFrame(
            {
                "Open": close - 0.3,
                "High": close + abs(np.random.randn(n) * 0.5),
                "Low": close - abs(np.random.randn(n) * 0.5),
                "Close": close,
                "Volume": np.random.randint(1_000_000, 5_000_000, n),
            },
            index=dates,
        )

    def test_returns_all_keys(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        expected_keys = {
            "rsi",
            "sma20",
            "sma50",
            "macd_line",
            "macd_signal",
            "macd_hist",
            "prev_macd_hist",
            "adx",
            "dmp",
            "dmn",
        }
        assert expected_keys.issubset(raw.keys())

    def test_rsi_in_range(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["rsi"] is not None
        assert 0 <= raw["rsi"] <= 100

    def test_sma_values(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["sma20"] is not None
        assert raw["sma50"] is not None
        assert isinstance(raw["sma20"], float)

    def test_macd_values(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["macd_line"] is not None
        assert raw["macd_signal"] is not None
        assert raw["macd_hist"] is not None
        assert raw["prev_macd_hist"] is not None

    def test_adx_values(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["adx"] is not None
        assert raw["dmp"] is not None
        assert raw["dmn"] is not None
        assert raw["adx"] >= 0

    def test_short_dataframe_returns_nones(self):
        df = self._make_df(n=5)
        raw = compute_raw_indicators(df)
        # With only 5 rows, most indicators can't compute
        # Should still return dict with None values rather than crashing
        assert isinstance(raw, dict)
        assert "rsi" in raw

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        raw = compute_raw_indicators(df)
        assert isinstance(raw, dict)
        assert raw["rsi"] is None

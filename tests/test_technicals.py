# ABOUTME: Tests for technical analysis module using real Yahoo Finance data.
# ABOUTME: Validates indicator computation, signal generation, and multi-symbol.


import numpy as np
import pandas as pd

from trading_skills.technicals import (
    compute_indicators,
    compute_multi_symbol,
    compute_raw_indicators,
    detect_ema_crossover,
    detect_macd_crossover,
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


class TestDetectMacdCrossover:
    """Tests for MACD crossover detection — uses synthetic histogram data."""

    def _make_macd_df(self, hist_values):
        """Minimal 3-column DataFrame matching pandas-ta macd() output layout."""
        n = len(hist_values)
        return pd.DataFrame(
            {
                "MACD_12_26_9": [1.0] * n,
                "MACDs_12_26_9": [0.5] * n,
                "MACDh_12_26_9": hist_values,
            }
        )

    def test_detects_up_crossover(self):
        df = self._make_macd_df([-2.0, -1.0, 1.0, 2.0])
        result = detect_macd_crossover(df)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 1

    def test_detects_down_crossover(self):
        df = self._make_macd_df([2.0, 1.0, -1.0, -2.0])
        result = detect_macd_crossover(df)
        assert result is not None
        assert result["direction"] == "down"
        assert result["days_ago"] == 1

    def test_crossover_at_current_bar(self):
        df = self._make_macd_df([-1.0, 1.0])
        result = detect_macd_crossover(df)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_returns_most_recent_crossover(self):
        # Two crossovers: down at index 2, up at index 3 (most recent)
        df = self._make_macd_df([-2.0, 1.0, -1.0, 2.0])
        result = detect_macd_crossover(df)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_no_crossover_all_positive(self):
        df = self._make_macd_df([1.0, 2.0, 3.0, 4.0])
        result = detect_macd_crossover(df)
        assert result is None

    def test_no_crossover_all_negative(self):
        df = self._make_macd_df([-4.0, -3.0, -2.0, -1.0])
        result = detect_macd_crossover(df)
        assert result is None

    def test_handles_leading_nans(self):
        df = self._make_macd_df([float("nan"), float("nan"), -1.0, 1.0])
        result = detect_macd_crossover(df)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_too_short_returns_none(self):
        df = self._make_macd_df([1.0])
        result = detect_macd_crossover(df)
        assert result is None

    def test_empty_returns_none(self):
        df = self._make_macd_df([])
        result = detect_macd_crossover(df)
        assert result is None


class TestDetectEmaCrossover:
    """Tests for EMA9/EMA21 crossover detection using synthetic Series."""

    def _make_series(self, values):
        return pd.Series(values, dtype=float)

    def test_detects_up_crossover(self):
        # ema9 crosses above ema21: diff goes negative to positive
        ema9 = self._make_series([8.0, 9.0, 11.0, 12.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 1

    def test_detects_down_crossover(self):
        # ema9 crosses below ema21
        ema9 = self._make_series([12.0, 11.0, 9.0, 8.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "down"
        assert result["days_ago"] == 1

    def test_crossover_at_current_bar(self):
        ema9 = self._make_series([9.0, 11.0])
        ema21 = self._make_series([10.0, 10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_returns_most_recent_crossover(self):
        # Two crossovers: down at index 2, up at index 3
        ema9 = self._make_series([9.0, 11.0, 9.0, 11.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_no_crossover_ema9_always_above(self):
        ema9 = self._make_series([11.0, 12.0, 13.0, 14.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is None

    def test_no_crossover_ema9_always_below(self):
        ema9 = self._make_series([9.0, 8.0, 7.0, 6.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is None

    def test_handles_leading_nans(self):
        ema9 = self._make_series([float("nan"), float("nan"), 9.0, 11.0])
        ema21 = self._make_series([float("nan"), float("nan"), 10.0, 10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_too_short_returns_none(self):
        ema9 = self._make_series([11.0])
        ema21 = self._make_series([10.0])
        result = detect_ema_crossover(ema9, ema21)
        assert result is None

    def test_empty_returns_none(self):
        result = detect_ema_crossover(self._make_series([]), self._make_series([]))
        assert result is None


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
            "macd_crossover",
            "ema9",
            "ema21",
            "ema_crossover",
            "adx",
            "dmp",
            "dmn",
        }
        assert expected_keys.issubset(raw.keys())

    def test_ema_values(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        assert raw["ema9"] is not None
        assert raw["ema21"] is not None
        assert isinstance(raw["ema9"], float)
        assert isinstance(raw["ema21"], float)

    def test_ema_crossover_structure(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        xover = raw["ema_crossover"]
        if xover is not None:
            assert xover["direction"] in ("up", "down")
            assert isinstance(xover["days_ago"], int)
            assert xover["days_ago"] >= 0

    def test_macd_crossover_structure(self):
        df = self._make_df()
        raw = compute_raw_indicators(df)
        xover = raw["macd_crossover"]
        if xover is not None:
            assert xover["direction"] in ("up", "down")
            assert isinstance(xover["days_ago"], int)
            assert xover["days_ago"] >= 0

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

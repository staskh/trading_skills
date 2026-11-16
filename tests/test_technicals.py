# ABOUTME: Tests for technical analysis module using real Yahoo Finance data.
# ABOUTME: Validates indicator computation, signal generation, and multi-symbol.


import numpy as np
import pandas as pd
import pandas_ta as ta
import pytest

from trading_skills.technicals import (
    adx_columns,
    compute_indicators,
    compute_multi_symbol,
    compute_raw_indicators,
    detect_crossover,
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

    def test_macd_output_includes_crossover(self):
        result = compute_indicators("AAPL", period="6mo")
        macd = result["indicators"]["macd"]
        assert "crossover" in macd
        if macd["crossover"] is not None:
            assert macd["crossover"]["direction"] in ("up", "down")
            assert isinstance(macd["crossover"]["days_ago"], int)

    def test_ema_output_includes_crossover(self):
        result = compute_indicators("AAPL", period="6mo")
        ema = result["indicators"]["ema"]
        assert "ema9" in ema
        assert "ema21" in ema
        assert "crossover" in ema
        if ema["crossover"] is not None:
            assert ema["crossover"]["direction"] in ("up", "down")
            assert isinstance(ema["crossover"]["days_ago"], int)

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

    def test_new_groups_present_when_requested(self):
        result = compute_indicators(
            "AAPL", period="2y", indicators=["sma200", "range52w", "structure", "pivots"]
        )
        groups = result["indicators"]
        assert set(groups) == {"sma200", "range52w", "structure", "pivots"}
        assert groups["sma200"]["source"] == "bars"
        assert groups["sma200"]["sma200"] is not None
        assert groups["range52w"]["source"] == "bars"
        assert groups["range52w"]["low_52w_prior"] is not None
        assert groups["range52w"]["pct_from_high"] <= 0
        assert len(groups["structure"]["recent_bars"]) == 5
        assert "current_levels" in groups["pivots"]

    def test_info_fallback_marks_source(self):
        result = compute_indicators("AAPL", period="3mo", indicators=["sma200", "range52w"])
        sma = result["indicators"]["sma200"]
        rng = result["indicators"]["range52w"]
        assert sma["sma200"] is not None
        assert sma["source"] == "info"
        assert sma["cross"] is None
        assert rng["high_52w"] is not None
        assert rng["source"] == "info"
        assert rng["low_52w_prior"] is None

    def test_default_groups_unchanged(self):
        result = compute_indicators("AAPL", period="3mo")
        assert set(result["indicators"]) == {
            "rsi",
            "macd",
            "bollinger",
            "sma",
            "ema",
            "atr",
            "adx",
        }

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


class TestAdxColumns:
    """Tests for ADX/DI column selection."""

    def test_selects_by_name_from_pandas_ta_layout(self):
        # pandas-ta adx() emits four columns including ADXR between ADX and DMP.
        df = pd.DataFrame(
            {
                "ADX_14": [20.0],
                "ADXR_14_2": [19.0],
                "DMP_14": [30.0],
                "DMN_14": [10.0],
            }
        )
        assert adx_columns(df) == ("ADX_14", "DMP_14", "DMN_14")

    def test_column_order_independent(self):
        df = pd.DataFrame(
            {
                "DMN_14": [10.0],
                "ADXR_14_2": [19.0],
                "ADX_14": [20.0],
                "DMP_14": [30.0],
            }
        )
        assert adx_columns(df) == ("ADX_14", "DMP_14", "DMN_14")

    def test_does_not_return_adxr(self):
        # ADXR starts with "ADX" too, so a naive prefix match could grab it.
        df = pd.DataFrame(
            {
                "ADXR_14_2": [19.0],
                "ADX_14": [20.0],
                "DMP_14": [30.0],
                "DMN_14": [10.0],
            }
        )
        assert "ADXR_14_2" not in adx_columns(df)

    def test_raw_indicators_di_reflect_directional_movement(self):
        # A strictly rising series has positive directional movement only, so
        # +DI must exceed -DI. Reading pandas-ta's columns positionally picks up
        # ADXR as +DI and DMP as -DI, which inverts this.
        n = 60
        close = pd.Series(np.linspace(100.0, 160.0, n))
        df = pd.DataFrame(
            {
                "Open": close,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": [1_000_000] * n,
            }
        )
        raw = compute_raw_indicators(df)
        assert raw["dmp"] > raw["dmn"]

        expected = ta.adx(df["High"], df["Low"], df["Close"], length=14)
        assert raw["dmp"] == pytest.approx(expected["DMP_14"].iloc[-1])
        assert raw["dmn"] == pytest.approx(expected["DMN_14"].iloc[-1])
        assert raw["adx"] == pytest.approx(expected["ADX_14"].iloc[-1])


class TestDetectMacdCrossover:
    """Tests for MACD crossover detection — uses synthetic histogram data."""

    def _make_macd_df(self, hist_values):
        """Minimal 3-column DataFrame matching pandas-ta macd() output layout.

        pandas-ta column order is [MACD_, MACDh_, MACDs_] = (line, histogram, signal).
        """
        n = len(hist_values)
        return pd.DataFrame(
            {
                "MACD_12_26_9": [1.0] * n,
                "MACDh_12_26_9": hist_values,
                "MACDs_12_26_9": [0.5] * n,
            }
        )

    def test_reads_histogram_column_not_signal(self):
        # Real pandas-ta layout: histogram crosses up at the last bar, while the
        # signal line stays constant and never crosses zero. A detector that reads
        # the signal column instead of the histogram would return None here.
        df = pd.DataFrame(
            {
                "MACD_12_26_9": [1.0, 1.0, 1.0],
                "MACDh_12_26_9": [-1.0, -0.5, 0.5],
                "MACDs_12_26_9": [2.0, 2.0, 2.0],
            }
        )
        result = detect_macd_crossover(df)
        assert result == {"direction": "up", "days_ago": 0}

    def test_column_order_independent(self):
        # Columns selected by name, so declaration order must not matter.
        df = pd.DataFrame(
            {
                "MACDs_12_26_9": [2.0, 2.0, 2.0],
                "MACD_12_26_9": [1.0, 1.0, 1.0],
                "MACDh_12_26_9": [1.0, 0.5, -0.5],
            }
        )
        result = detect_macd_crossover(df)
        assert result == {"direction": "down", "days_ago": 0}

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
        result = detect_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 1

    def test_detects_down_crossover(self):
        # ema9 crosses below ema21
        ema9 = self._make_series([12.0, 11.0, 9.0, 8.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "down"
        assert result["days_ago"] == 1

    def test_crossover_at_current_bar(self):
        ema9 = self._make_series([9.0, 11.0])
        ema21 = self._make_series([10.0, 10.0])
        result = detect_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_returns_most_recent_crossover(self):
        # Two crossovers: down at index 2, up at index 3
        ema9 = self._make_series([9.0, 11.0, 9.0, 11.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_no_crossover_ema9_always_above(self):
        ema9 = self._make_series([11.0, 12.0, 13.0, 14.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_crossover(ema9, ema21)
        assert result is None

    def test_no_crossover_ema9_always_below(self):
        ema9 = self._make_series([9.0, 8.0, 7.0, 6.0])
        ema21 = self._make_series([10.0, 10.0, 10.0, 10.0])
        result = detect_crossover(ema9, ema21)
        assert result is None

    def test_handles_leading_nans(self):
        ema9 = self._make_series([float("nan"), float("nan"), 9.0, 11.0])
        ema21 = self._make_series([float("nan"), float("nan"), 10.0, 10.0])
        result = detect_crossover(ema9, ema21)
        assert result is not None
        assert result["direction"] == "up"
        assert result["days_ago"] == 0

    def test_too_short_returns_none(self):
        ema9 = self._make_series([11.0])
        ema21 = self._make_series([10.0])
        result = detect_crossover(ema9, ema21)
        assert result is None

    def test_empty_returns_none(self):
        result = detect_crossover(self._make_series([]), self._make_series([]))
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

    def test_macd_columns_mapped_to_correct_names(self):
        # signal must come from MACDs_, histogram from MACDh_ — not positionally swapped.
        df = self._make_df()
        macd = ta.macd(df["Close"])
        raw = compute_raw_indicators(df)
        assert raw["macd_line"] == pytest.approx(macd["MACD_12_26_9"].iloc[-1])
        assert raw["macd_signal"] == pytest.approx(macd["MACDs_12_26_9"].iloc[-1])
        assert raw["macd_hist"] == pytest.approx(macd["MACDh_12_26_9"].iloc[-1])
        assert raw["prev_macd_hist"] == pytest.approx(macd["MACDh_12_26_9"].iloc[-2])
        # Defining identity of MACD: histogram = line - signal.
        assert raw["macd_hist"] == pytest.approx(raw["macd_line"] - raw["macd_signal"])

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


def _ohlcv(close, high=None, low=None):
    close = np.asarray(close, dtype=float)
    n = len(close)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1 if high is None else np.asarray(high, dtype=float),
            "Low": close - 1 if low is None else np.asarray(low, dtype=float),
            "Close": close,
            "Volume": np.full(n, 1_000_000),
        },
        index=pd.bdate_range("2024-01-01", periods=n),
    )


class TestTrendIndicators:
    """Raw trend indicators on constructed frames with known answers."""

    def test_sma_cross_dated(self):
        close = np.full(300, 100.0)
        close[287:] = 50.0
        raw = compute_raw_indicators(_ohlcv(close))
        assert raw["sma_cross"] == {"direction": "down", "days_ago": 12}
        assert raw["sma200"] == pytest.approx(close[-200:].mean())

    def test_closes_below_sma50_counts_last_five(self):
        close = np.full(100, 100.0)
        close[-5:] = [105, 95, 105, 95, 95]
        raw = compute_raw_indicators(_ohlcv(close))
        assert raw["closes_below_sma50"] == 3

    def test_lower_highs_and_lows(self):
        down = compute_raw_indicators(_ohlcv(np.linspace(200, 100, 100)))
        assert down["lower_highs"] is True
        assert down["lower_lows"] is True
        up = compute_raw_indicators(_ohlcv(np.linspace(100, 200, 100)))
        assert up["lower_highs"] is False
        assert up["lower_lows"] is False

    def test_52w_range_and_prior_low(self):
        n = 300
        close = np.full(n, 100.0)
        high = np.full(n, 110.0)
        low = np.full(n, 90.0)
        low[0] = 10.0  # older than 252 bars: ignored
        high[-100] = 150.0
        low[-10] = 50.0
        low[-1] = 40.0  # last bar: excluded from the prior low
        raw = compute_raw_indicators(_ohlcv(close, high, low))
        assert raw["high_52w"] == 150.0
        assert raw["low_52w"] == 40.0
        assert raw["low_52w_prior"] == 50.0

    def test_rsi_recent_and_recent_bars_length_five(self):
        raw = compute_raw_indicators(_ohlcv(np.linspace(100, 200, 100)))
        assert len(raw["rsi_recent"]) == 5
        assert raw["rsi_recent"][-1] == pytest.approx(raw["rsi"])
        bars = raw["recent_bars"]
        assert len(bars) == 5
        assert set(bars[-1]) == {"date", "open", "high", "low", "close"}
        assert bars[-1]["close"] == 200.0
        assert bars[-1]["date"] == str(pd.bdate_range("2024-01-01", periods=100)[-1].date())

    def test_return_3m_pct(self):
        close = np.arange(100.0, 400.0)
        raw = compute_raw_indicators(_ohlcv(close))
        assert raw["return_3m_pct"] == pytest.approx((close[-1] / close[-64] - 1) * 100)

    def test_short_history_gives_none(self):
        raw = compute_raw_indicators(_ohlcv(np.linspace(100, 200, 100)))
        for key in ("sma200", "sma_cross", "high_52w", "low_52w", "low_52w_prior"):
            assert raw[key] is None
        assert raw["lower_highs"] is not None
        assert raw["return_3m_pct"] is not None

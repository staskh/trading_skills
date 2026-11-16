# ABOUTME: Tests for the indicator functions in trading_skills.ta (backed by fin-primitives).
# ABOUTME: Checks values against TA-Lib, warm-up lengths, missing bars and the pandas-ta layout.

import numpy as np
import pandas as pd
import pytest

from trading_skills import ta
from trading_skills.technicals import adx_columns, macd_columns


def _bars(n: int) -> pd.DataFrame:
    """Deterministic daily OHLC bars: a rising wave with noise, so every indicator moves."""
    i = np.arange(n, dtype=float)
    close = 100 + 8 * np.sin(i / 9) + 0.15 * i + 1.5 * np.sin(i * 1.7)
    return pd.DataFrame(
        {
            "High": close + 0.6 + 0.4 * np.abs(np.sin(i * 0.9)),
            "Low": close - 0.6 - 0.4 * np.abs(np.cos(i * 1.3)),
            "Close": close,
        },
        index=pd.bdate_range("2026-01-02", periods=n),
    )


def _all(df: pd.DataFrame) -> dict[str, pd.Series]:
    h, lo, c = df["High"], df["Low"], df["Close"]
    m = ta.macd(c)
    bb = ta.bbands(c, length=20, std=2)
    a = ta.adx(h, lo, c, length=14)
    return {
        "rsi": ta.rsi(c, length=14),
        "ema9": ta.ema(c, length=9),
        "sma20": ta.sma(c, length=20),
        "macd": m["MACD_12_26_9"],
        "macds": m["MACDs_12_26_9"],
        "macdh": m["MACDh_12_26_9"],
        "bbl": bb.iloc[:, 0],
        "bbm": bb.iloc[:, 1],
        "bbu": bb.iloc[:, 2],
        "atr": ta.atr(h, lo, c, length=14),
        "adx": a["ADX_14"],
        "dmp": a["DMP_14"],
        "dmn": a["DMN_14"],
    }


# Last-bar values from TA-Lib 0.6.8 (RSI, EMA, SMA, BBANDS(20, 2, 2), ATR, ADX, PLUS_DI,
# MINUS_DI) on _bars(n). MACD is EMA(12) - EMA(26) with an EMA(9) signal of that line, built
# from talib.EMA; talib.MACD itself starts the fast EMA late, so its first ~40 bars differ.
# Three months of daily bars is about 65 bars, which is where the warm-up seeding shows.
TALIB_LAST = {
    65: {
        "rsi": 73.5282294849,
        "ema9": 112.1338343476,
        "sma20": 106.8140431499,
        "macd": 3.3947029811,
        "macds": 2.2259879775,
        "macdh": 1.1687150037,
        "bbl": 96.0054238507,
        "bbm": 106.8140431499,
        "bbu": 117.6226624492,
        "atr": 2.5130330754,
        "adx": 24.76209422,
        "dmp": 45.3056181082,
        "dmn": 16.586773298,
    },
    120: {
        "rsi": 72.3312454185,
        "ema9": 119.1315412114,
        "sma20": 113.9812961024,
        "macd": 3.0652452982,
        "macds": 1.8790920517,
        "macdh": 1.1861532466,
        "bbl": 103.6577625365,
        "bbm": 113.9812961024,
        "bbu": 124.3048296684,
        "atr": 2.5364091944,
        "adx": 21.9514740003,
        "dmp": 44.2174499267,
        "dmn": 17.2655753132,
    },
}

# Leading NaNs per indicator, equal to TA-Lib's lookback for the same parameters.
WARMUP = {
    "rsi": 14,
    "ema9": 8,
    "sma20": 19,
    "macd": 25,
    "macds": 33,
    "macdh": 33,
    "bbl": 19,
    "bbm": 19,
    "bbu": 19,
    "atr": 14,
    "adx": 27,
    "dmp": 14,
    "dmn": 14,
}


@pytest.mark.parametrize("n", sorted(TALIB_LAST))
def test_last_values_match_talib(n):
    values = _all(_bars(n))
    for key, expected in TALIB_LAST[n].items():
        assert values[key].iloc[-1] == pytest.approx(expected, abs=1e-8), key


def test_warmup_matches_talib_lookback():
    values = _all(_bars(65))
    for key, nans in WARMUP.items():
        series = values[key]
        assert series.iloc[:nans].isna().all(), key
        assert series.iloc[nans:].notna().all(), key


def test_outputs_keep_the_input_index():
    df = _bars(40)
    for key, series in _all(df).items():
        assert series.index.equals(df.index), key


def test_macd_histogram_is_line_minus_signal():
    m = ta.macd(_bars(65)["Close"])
    line, hist, signal = macd_columns(m)
    pd.testing.assert_series_equal(
        m[hist].dropna(), (m[line] - m[signal]).dropna(), check_names=False
    )


def test_adx_frame_has_the_columns_technicals_reads():
    df = _bars(65)
    a = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    assert adx_columns(a) == ("ADX_14", "DMP_14", "DMN_14")


def test_rising_series_has_only_positive_directional_movement():
    close = pd.Series(np.linspace(100.0, 160.0, 60))
    a = ta.adx(close + 1.0, close - 1.0, close, length=14)
    assert (a["DMN_14"].dropna() == 0).all()
    assert a["DMP_14"].iloc[-1] > 0
    # +DM and TR grow together, so DX is 100 every bar and so is its average.
    assert a["ADX_14"].iloc[-1] == pytest.approx(100.0)


def test_missing_bar_is_skipped():
    df = _bars(65)
    gap = df.copy()
    gap.iloc[40, :] = np.nan
    with_gap = _all(gap)
    without = _all(df.drop(df.index[40]))
    for key, series in with_gap.items():
        assert np.isnan(series.iloc[40]), key
        pd.testing.assert_series_equal(
            series.drop(df.index[40]), without[key], check_names=False, obj=key
        )


@pytest.mark.parametrize("n", [0, 1, 5])
def test_short_input_returns_nan_without_raising(n):
    values = _all(_bars(n))
    for key, series in values.items():
        assert len(series) == n, key
        assert series.isna().all(), key


def test_flat_prices_give_zero_directional_index():
    close = pd.Series([50.0] * 40)
    a = ta.adx(close, close, close, length=14)
    assert (a["DMP_14"].dropna() == 0).all()
    assert (a["DMN_14"].dropna() == 0).all()
    assert (a["ADX_14"].dropna() == 0).all()
    assert ta.atr(close, close, close).iloc[-1] == 0

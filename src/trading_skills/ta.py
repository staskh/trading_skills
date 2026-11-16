# ABOUTME: Technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, ATR, ADX/DMI) on pandas data.
# ABOUTME: Computed by fin-primitives; values match TA-Lib, frame layouts match pandas-ta.

import fin_primitives as fp
import numpy as np
import pandas as pd

# Every function returns one value per input row, NaN while the indicator warms up.
# Rows with a missing price are skipped (they get NaN) instead of breaking the series.


def _run(kind: str, values: np.ndarray, length: int) -> np.ndarray:
    """Run a fin-primitives indicator over a float array that has no NaNs."""
    if len(values) == 0:
        return np.empty(0)
    return fp.compute(kind, values, length, mode="float")


def _series(kind: str, close: pd.Series, length: int, name: str) -> pd.Series:
    """Run an indicator over the non-missing values of `close`, aligned to its index."""
    values = close.to_numpy(dtype=float, na_value=np.nan)
    valid = ~np.isnan(values)
    out = np.full(len(values), np.nan)
    out[valid] = _run(kind, values[valid], length)
    return pd.Series(out, index=close.index, name=name)


def sma(close: pd.Series, length: int = 20) -> pd.Series:
    """Simple moving average."""
    return _series("sma", close, length, f"SMA_{length}")


def ema(close: pd.Series, length: int = 20) -> pd.Series:
    """Exponential moving average, seeded with the SMA of the first `length` values."""
    return _series("ema", close, length, f"EMA_{length}")


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's RSI (0-100), seeded with the average gain and loss of the first `length` bars."""
    return _series("rsi", close, length, f"RSI_{length}")


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, histogram and signal as MACD_, MACDh_, MACDs_ columns.

    The line is EMA(fast) - EMA(slow); the signal is the EMA of the line from its first value.
    """
    line = ema(close, fast) - ema(close, slow)
    sig = _series("ema", line, signal, "")
    suffix = f"{fast}_{slow}_{signal}"
    return pd.DataFrame(
        {f"MACD_{suffix}": line, f"MACDh_{suffix}": line - sig, f"MACDs_{suffix}": sig},
        index=close.index,
    )


def bbands(close: pd.Series, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands as lower, middle, upper columns (population standard deviation)."""
    mid = sma(close, length)
    dev = _series("std_dev", close, length, "")
    suffix = f"{length}_{float(std)}"
    return pd.DataFrame(
        {f"BBL_{suffix}": mid - std * dev, f"BBM_{suffix}": mid, f"BBU_{suffix}": mid + std * dev},
        index=close.index,
    )


def _bars(high: pd.Series, low: pd.Series, close: pd.Series):
    """The rows where high, low and close are all present, as float arrays."""
    frame = pd.concat([high, low, close], axis=1).to_numpy(dtype=float, na_value=np.nan)
    valid = ~np.isnan(frame).any(axis=1)
    h, lo, c = frame[valid].T
    return valid, h, lo, c


def _directional(h: np.ndarray, lo: np.ndarray, c: np.ndarray):
    """True range, +DM and -DM per bar; all 0 on the first bar, which has no prior bar."""
    n = len(c)
    tr, plus, minus = np.zeros(n), np.zeros(n), np.zeros(n)
    if n > 1:
        prev = c[:-1]
        tr[1:] = np.maximum(h[1:] - lo[1:], np.maximum(np.abs(h[1:] - prev), np.abs(lo[1:] - prev)))
        up, down = h[1:] - h[:-1], lo[:-1] - lo[1:]
        plus[1:] = np.where((up > down) & (up > 0), up, 0.0)
        minus[1:] = np.where((down > up) & (down > 0), down, 0.0)
    return tr, plus, minus


def _scatter(valid: np.ndarray, values: np.ndarray, index: pd.Index, name: str) -> pd.Series:
    out = np.full(len(valid), np.nan)
    out[valid] = values
    return pd.Series(out, index=index, name=name)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average true range with Wilder smoothing, starting from the second bar."""
    valid, h, lo, c = _bars(high, low, close)
    tr, _, _ = _directional(h, lo, c)
    values = np.full(len(c), np.nan)
    if len(c) > 1:
        values[1:] = _run("smma", tr[1:], length)
    return _scatter(valid, values, close.index, f"ATRr_{length}")


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.DataFrame:
    """Wilder's ADX with +DI and -DI as ADX_, DMP_, DMN_ columns.

    +DM, -DM and true range are Wilder-smoothed from the second bar; the zero first bar makes
    the smoothing start from the sum of the first `length - 1` values, as Wilder and TA-Lib do.
    DI is defined from bar `length` and ADX (the smoothed DX) from bar `2 * length - 1`.
    """
    valid, h, lo, c = _bars(high, low, close)
    n = len(c)
    tr, plus, minus = _directional(h, lo, c)
    s_tr, s_plus, s_minus = (_run("smma", x, length) for x in (tr, plus, minus))
    di_plus, di_minus, dx = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    adx_values = np.full(n, np.nan)
    if n > length:
        rng = slice(length, None)
        with np.errstate(divide="ignore", invalid="ignore"):
            di_plus[rng] = np.where(s_tr[rng] > 0, 100 * s_plus[rng] / s_tr[rng], 0.0)
            di_minus[rng] = np.where(s_tr[rng] > 0, 100 * s_minus[rng] / s_tr[rng], 0.0)
            total = di_plus[rng] + di_minus[rng]
            dx[rng] = np.where(total > 0, 100 * np.abs(di_plus[rng] - di_minus[rng]) / total, 0.0)
        adx_values[rng] = _run("smma", dx[rng], length)
    return pd.DataFrame(
        {
            f"ADX_{length}": _scatter(valid, adx_values, close.index, ""),
            f"DMP_{length}": _scatter(valid, di_plus, close.index, ""),
            f"DMN_{length}": _scatter(valid, di_minus, close.index, ""),
        },
        index=close.index,
    )

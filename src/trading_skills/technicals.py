# ABOUTME: Computes technical indicators using pandas-ta.
# ABOUTME: Supports multi-symbol analysis and earnings data.

from zoneinfo import ZoneInfo

import pandas as pd
import pandas_ta as ta
import yfinance as yf

from trading_skills.earnings import get_next_earnings_date
from trading_skills.pivots import completed_bars, is_partial_session, pivot_status
from trading_skills.utils import annualized_volatility

NY = ZoneInfo("America/New_York")


def get_earnings_data(symbol: str) -> dict:
    """Get upcoming and historical earnings data for a symbol."""
    ticker = yf.Ticker(symbol)
    result = {"symbol": symbol.upper()}

    # Get upcoming earnings date
    upcoming = get_next_earnings_date(symbol)
    if upcoming:
        result["upcoming"] = upcoming

    # Get historical earnings
    try:
        earnings_dates = ticker.earnings_dates
        if earnings_dates is not None and not earnings_dates.empty:
            history = []
            for idx in earnings_dates.head(8).index:
                row = earnings_dates.loc[idx]
                entry = {"date": str(idx.date()) if hasattr(idx, "date") else str(idx)}

                if "EPS Estimate" in row and pd.notna(row["EPS Estimate"]):
                    entry["estimated_eps"] = round(float(row["EPS Estimate"]), 3)
                if "Reported EPS" in row and pd.notna(row["Reported EPS"]):
                    entry["reported_eps"] = round(float(row["Reported EPS"]), 3)
                if "Surprise(%)" in row and pd.notna(row["Surprise(%)"]):
                    entry["surprise_pct"] = round(float(row["Surprise(%)"]), 2)

                if "estimated_eps" in entry or "reported_eps" in entry:
                    history.append(entry)

            if history:
                result["history"] = history
    except Exception:
        pass

    return result


def macd_columns(macd_df: pd.DataFrame) -> tuple[str, str, str]:
    """Return the (line, histogram, signal) column labels of a pandas-ta macd() frame.

    pandas-ta names them MACD_, MACDh_, MACDs_ and orders them (line, histogram,
    signal). Selecting by name prefix avoids depending on positional order.
    """
    line = next(c for c in macd_df.columns if c.startswith("MACD_"))
    hist = next(c for c in macd_df.columns if c.startswith("MACDh_"))
    signal = next(c for c in macd_df.columns if c.startswith("MACDs_"))
    return line, hist, signal


def adx_columns(adx_df: pd.DataFrame) -> tuple[str, str, str]:
    """Return the (adx, +di, -di) column labels of a pandas-ta adx() frame.

    pandas-ta names them ADX_, ADXR_, DMP_, DMN_ and places ADXR between the
    ADX and DMP columns. Selecting by name avoids depending on positional
    order, and the ADXR_ guard keeps the ADX_ prefix match from claiming it.
    """
    adx = next(c for c in adx_df.columns if c.startswith("ADX_") and not c.startswith("ADXR_"))
    dmp = next(c for c in adx_df.columns if c.startswith("DMP_"))
    dmn = next(c for c in adx_df.columns if c.startswith("DMN_"))
    return adx, dmp, dmn


def detect_macd_crossover(macd_df: pd.DataFrame) -> dict | None:
    """Find the most recent MACD crossover in a pandas-ta macd() DataFrame.

    Scans the histogram column (MACD line minus signal) for sign changes.
    Returns {"direction": "up"|"down", "days_ago": int} or None if no
    crossover is found. "days_ago" is trading bars since the crossover bar.
    """
    if macd_df is None or macd_df.empty:
        return None

    _, hist_col, _ = macd_columns(macd_df)
    hist = macd_df[hist_col].dropna()
    if len(hist) < 2:
        return None

    values = hist.to_numpy()
    for i in range(len(values) - 1, 0, -1):
        curr, prev = values[i], values[i - 1]
        if curr > 0 and prev <= 0:
            return {"direction": "up", "days_ago": len(values) - 1 - i}
        if curr < 0 and prev >= 0:
            return {"direction": "down", "days_ago": len(values) - 1 - i}

    return None


def detect_crossover(fast: pd.Series, slow: pd.Series) -> dict | None:
    """Find the most recent crossover between two series (e.g. EMA9 vs EMA21, SMA50 vs SMA200).

    Returns {"direction": "up"|"down", "days_ago": int} or None if no crossover
    is found. "up" means fast crossed above slow (bullish).
    "days_ago" is trading bars since the crossover bar.
    """
    diff = (fast - slow).dropna()
    if len(diff) < 2:
        return None

    values = diff.to_numpy()
    for i in range(len(values) - 1, 0, -1):
        curr, prev = values[i], values[i - 1]
        if curr > 0 and prev <= 0:
            return {"direction": "up", "days_ago": len(values) - 1 - i}
        if curr < 0 and prev >= 0:
            return {"direction": "down", "days_ago": len(values) - 1 - i}

    return None


def compute_raw_indicators(df: pd.DataFrame) -> dict:
    """Extract raw technical indicator values from an OHLCV DataFrame.

    Returns dict with keys: rsi, sma20, sma50, macd_line, macd_signal,
    macd_hist, prev_macd_hist, adx, dmp, dmn. Values are None when
    insufficient data.
    """
    result = {
        "rsi": None,
        "sma20": None,
        "sma50": None,
        "macd_line": None,
        "macd_signal": None,
        "macd_hist": None,
        "prev_macd_hist": None,
        "macd_crossover": None,
        "ema9": None,
        "ema21": None,
        "ema_crossover": None,
        "adx": None,
        "dmp": None,
        "dmn": None,
        "sma200": None,
        "sma_cross": None,
        "high_52w": None,
        "low_52w": None,
        "low_52w_prior": None,
        "closes_below_sma50": None,
        "lower_highs": None,
        "lower_lows": None,
        "rsi_recent": None,
        "recent_bars": None,
        "return_3m_pct": None,
    }

    if df.empty or "Close" not in df.columns:
        return result

    close = df["Close"]

    # RSI
    rsi = ta.rsi(close, length=14)
    if rsi is not None and len(rsi) > 0:
        val = rsi.iloc[-1]
        if pd.notna(val):
            result["rsi"] = float(val)

    # SMA
    sma20 = ta.sma(close, length=20)
    if sma20 is not None and len(sma20) > 0:
        val = sma20.iloc[-1]
        if pd.notna(val):
            result["sma20"] = float(val)

    sma50 = ta.sma(close, length=50)
    if sma50 is not None and len(sma50) > 0:
        val = sma50.iloc[-1]
        if pd.notna(val):
            result["sma50"] = float(val)

    # EMA9 / EMA21
    ema9_series = ta.ema(close, length=9)
    ema21_series = ta.ema(close, length=21)
    if ema9_series is not None and len(ema9_series) > 0:
        val = ema9_series.iloc[-1]
        if pd.notna(val):
            result["ema9"] = float(val)
    if ema21_series is not None and len(ema21_series) > 0:
        val = ema21_series.iloc[-1]
        if pd.notna(val):
            result["ema21"] = float(val)
    if ema9_series is not None and ema21_series is not None:
        result["ema_crossover"] = detect_crossover(ema9_series, ema21_series)

    # MACD
    macd = ta.macd(close)
    if macd is not None and len(macd) > 0:
        line_col, hist_col, signal_col = macd_columns(macd)
        line = macd[line_col].iloc[-1]
        signal = macd[signal_col].iloc[-1]
        hist = macd[hist_col].iloc[-1]
        if pd.notna(line):
            result["macd_line"] = float(line)
        if pd.notna(signal):
            result["macd_signal"] = float(signal)
        if pd.notna(hist):
            result["macd_hist"] = float(hist)
        if len(macd) > 1:
            prev = macd[hist_col].iloc[-2]
            if pd.notna(prev):
                result["prev_macd_hist"] = float(prev)
        result["macd_crossover"] = detect_macd_crossover(macd)

    # ADX
    if "High" in df.columns and "Low" in df.columns:
        adx = ta.adx(df["High"], df["Low"], close, length=14)
        if adx is not None and len(adx) > 0:
            adx_col, dmp_col, dmn_col = adx_columns(adx)
            adx_val = adx[adx_col].iloc[-1]
            dmp_val = adx[dmp_col].iloc[-1]
            dmn_val = adx[dmn_col].iloc[-1]
            if pd.notna(adx_val):
                result["adx"] = float(adx_val)
            if pd.notna(dmp_val):
                result["dmp"] = float(dmp_val)
            if pd.notna(dmn_val):
                result["dmn"] = float(dmn_val)

    # Trend structure
    n = len(close)
    if n >= 200:
        sma200_series = ta.sma(close, length=200)
        result["sma200"] = float(sma200_series.iloc[-1])
        result["sma_cross"] = detect_crossover(ta.sma(close, length=50), sma200_series)

    if n >= 64:
        result["return_3m_pct"] = float((close.iloc[-1] / close.iloc[-64] - 1) * 100)

    if n >= 50:
        below = close.iloc[-5:] < ta.sma(close, length=50).iloc[-5:]
        result["closes_below_sma50"] = int(below.sum())

    if rsi is not None and len(rsi.dropna()) >= 5:
        result["rsi_recent"] = [float(v) for v in rsi.iloc[-5:]]

    if all(c in df.columns for c in ("Open", "High", "Low")) and n >= 5:
        result["recent_bars"] = [
            {
                "date": pd.Timestamp(idx).strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
            }
            for idx, row in df.iloc[-5:].iterrows()
        ]

    if "High" in df.columns and "Low" in df.columns:
        high, low = df["High"], df["Low"]
        if n >= 60:
            old, mid, new = (slice(-60, -40), slice(-40, -20), slice(-20, None))
            result["lower_highs"] = bool(
                high.iloc[old].max() > high.iloc[mid].max() > high.iloc[new].max()
            )
            result["lower_lows"] = bool(
                low.iloc[old].min() > low.iloc[mid].min() > low.iloc[new].min()
            )
        if n >= 252:
            result["high_52w"] = float(high.iloc[-252:].max())
            result["low_52w"] = float(low.iloc[-252:].min())
            result["low_52w_prior"] = float(low.iloc[-254:-2].min())

    return result


def _ticker_info(ticker: yf.Ticker) -> dict:
    """Return ticker.info, or an empty dict when Yahoo does not provide it."""
    try:
        return ticker.info or {}
    except Exception:
        return {}


def _fill_from_info(values: dict, info: dict, fields: dict[str, str]) -> tuple[dict, bool]:
    """Fill the None entries of `values` from `info`; `fields` maps value key to info key.

    Values already present are kept. Returns the filled values and whether any
    value actually came from `info`.
    """
    filled = dict(values)
    from_info = False
    for key, info_key in fields.items():
        if filled[key] is None and info.get(info_key) is not None:
            filled[key] = info[info_key]
            from_info = True
    return filled, from_info


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def compute_indicators(
    symbol: str,
    period: str = "3mo",
    indicators: list[str] | None = None,
    include_earnings: bool = False,
    completed_sessions: bool = False,
) -> dict:
    """Compute technical indicators for a symbol.

    With `completed_sessions` the indicator groups ignore today's partial session, so
    "closes" are never the live intraday price; `as_of` is the last bar they used.
    """
    if indicators is None:
        indicators = ["rsi", "macd", "bb", "sma", "ema", "atr", "adx"]

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)
    df = df.dropna(subset=["Close"])

    if df.empty:
        return {"error": f"No data for {symbol}"}

    result = {
        "symbol": symbol.upper(),
        "period": period,
        "price": {
            "current": round(df["Close"].iloc[-1], 2),
            "change": round(df["Close"].iloc[-1] - df["Close"].iloc[-2], 2),
            "change_pct": round((df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100, 2),
        },
        "indicators": {},
        "signals": [],
    }

    full_df = df
    if completed_sessions:
        df = completed_bars(df)
        result["as_of"] = df.index[-1].strftime("%Y-%m-%d")

    raw = compute_raw_indicators(df)

    # RSI
    if "rsi" in indicators and raw["rsi"] is not None:
        current_rsi = raw["rsi"]
        result["indicators"]["rsi"] = {
            "value": round(current_rsi, 2),
            "period": 14,
        }
        if current_rsi > 70:
            result["signals"].append(
                {"indicator": "RSI", "signal": "overbought", "value": round(current_rsi, 2)}
            )
        elif current_rsi < 30:
            result["signals"].append(
                {"indicator": "RSI", "signal": "oversold", "value": round(current_rsi, 2)}
            )

    # MACD
    if "macd" in indicators and raw["macd_line"] is not None:
        result["indicators"]["macd"] = {
            "macd": round(raw["macd_line"], 4),
            "signal": round(raw["macd_signal"], 4),
            "histogram": round(raw["macd_hist"], 4),
            "crossover": raw["macd_crossover"],
        }
        if raw["prev_macd_hist"] is not None:
            if raw["prev_macd_hist"] < 0 and raw["macd_hist"] > 0:
                result["signals"].append({"indicator": "MACD", "signal": "bullish_crossover"})
            elif raw["prev_macd_hist"] > 0 and raw["macd_hist"] < 0:
                result["signals"].append({"indicator": "MACD", "signal": "bearish_crossover"})

    # Bollinger Bands (not in compute_raw_indicators — BB/EMA/ATR are unique to this function)
    if "bb" in indicators:
        bb = ta.bbands(df["Close"], length=20, std=2)
        if bb is not None and len(bb) > 0:
            lower = bb.iloc[-1, 0]
            mid = bb.iloc[-1, 1]
            upper = bb.iloc[-1, 2]
            current_price = df["Close"].iloc[-1]
            result["indicators"]["bollinger"] = {
                "lower": round(lower, 2),
                "middle": round(mid, 2),
                "upper": round(upper, 2),
                "bandwidth": round((upper - lower) / mid * 100, 2),
            }
            if current_price < lower:
                result["signals"].append({"indicator": "BB", "signal": "below_lower_band"})
            elif current_price > upper:
                result["signals"].append({"indicator": "BB", "signal": "above_upper_band"})

    # SMA
    if "sma" in indicators:
        result["indicators"]["sma"] = {}
        if raw["sma20"] is not None:
            result["indicators"]["sma"]["sma20"] = round(raw["sma20"], 2)
        if raw["sma50"] is not None:
            result["indicators"]["sma"]["sma50"] = round(raw["sma50"], 2)
            # Golden/death cross needs previous values — compute locally
            sma20 = ta.sma(df["Close"], length=20)
            sma50 = ta.sma(df["Close"], length=50)
            if sma20 is not None and sma50 is not None and len(sma20) > 1 and len(sma50) > 1:
                if sma20.iloc[-2] < sma50.iloc[-2] and sma20.iloc[-1] > sma50.iloc[-1]:
                    result["signals"].append({"indicator": "SMA", "signal": "golden_cross"})
                elif sma20.iloc[-2] > sma50.iloc[-2] and sma20.iloc[-1] < sma50.iloc[-1]:
                    result["signals"].append({"indicator": "SMA", "signal": "death_cross"})

    # EMA
    if "ema" in indicators:
        ema12 = ta.ema(df["Close"], length=12)
        ema26 = ta.ema(df["Close"], length=26)
        result["indicators"]["ema"] = {}
        if ema12 is not None and len(ema12) > 0:
            result["indicators"]["ema"]["ema12"] = round(ema12.iloc[-1], 2)
        if ema26 is not None and len(ema26) > 0:
            result["indicators"]["ema"]["ema26"] = round(ema26.iloc[-1], 2)
        if raw["ema9"] is not None:
            result["indicators"]["ema"]["ema9"] = round(raw["ema9"], 2)
        if raw["ema21"] is not None:
            result["indicators"]["ema"]["ema21"] = round(raw["ema21"], 2)
        result["indicators"]["ema"]["crossover"] = raw["ema_crossover"]

    # ATR
    if "atr" in indicators:
        atr = ta.atr(df["High"], df["Low"], df["Close"], length=14)
        if atr is not None and len(atr) > 0:
            result["indicators"]["atr"] = {
                "value": round(atr.iloc[-1], 2),
                "percent": round(atr.iloc[-1] / df["Close"].iloc[-1] * 100, 2),
            }

    # ADX
    if "adx" in indicators and raw["adx"] is not None:
        result["indicators"]["adx"] = {
            "adx": round(raw["adx"], 2),
            "dmp": round(raw["dmp"], 2),
            "dmn": round(raw["dmn"], 2),
        }
        if raw["adx"] > 25:
            result["signals"].append(
                {
                    "indicator": "ADX",
                    "signal": "strong_trend",
                    "value": round(raw["adx"], 2),
                }
            )

    # SMA50/SMA200 trend. `source` is "info" when at least one value in the group
    # came from Yahoo's precomputed averages because the bars were too short.
    if "sma200" in indicators:
        values = {"sma50": raw["sma50"], "sma200": raw["sma200"]}
        from_info = False
        if None in values.values():
            values, from_info = _fill_from_info(
                values,
                _ticker_info(ticker),
                {"sma50": "fiftyDayAverage", "sma200": "twoHundredDayAverage"},
            )
        result["indicators"]["sma200"] = {
            "sma50": _round_or_none(values["sma50"]),
            "sma200": _round_or_none(values["sma200"]),
            "cross": raw["sma_cross"],
            "source": "info" if from_info else "bars",
        }

    # 52-week range. `source` is "info" when at least one value in the group
    # came from Yahoo's 52-week high/low because the bars were too short.
    if "range52w" in indicators:
        values = {"high_52w": raw["high_52w"], "low_52w": raw["low_52w"]}
        from_info = False
        if None in values.values():
            values, from_info = _fill_from_info(
                values,
                _ticker_info(ticker),
                {"high_52w": "fiftyTwoWeekHigh", "low_52w": "fiftyTwoWeekLow"},
            )
        pct_from_high = None
        if values["high_52w"] is not None:
            pct_from_high = round((result["price"]["current"] / values["high_52w"] - 1) * 100, 2)
        result["indicators"]["range52w"] = {
            "high_52w": _round_or_none(values["high_52w"]),
            "low_52w": _round_or_none(values["low_52w"]),
            "low_52w_prior": _round_or_none(raw["low_52w_prior"]),
            "pct_from_high": pct_from_high,
            "source": "info" if from_info else "bars",
        }

    # Swing structure over the recent sessions
    if "structure" in indicators:
        result["indicators"]["structure"] = {
            "closes_below_sma50": raw["closes_below_sma50"],
            "lower_highs": raw["lower_highs"],
            "lower_lows": raw["lower_lows"],
            "rsi_recent": raw["rsi_recent"],
            "recent_bars": raw["recent_bars"],
            "return_3m_pct": _round_or_none(raw["return_3m_pct"]),
            "macd_hist": raw["macd_hist"],
            "prev_macd_hist": raw["prev_macd_hist"],
        }

    # Pivot levels and entry status
    if "pivots" in indicators:
        pivots = None
        if len(full_df) >= 2:
            partial = len(full_df) >= 3 and is_partial_session(full_df)
            pivots = pivot_status(full_df, drop_today_partial=partial)
        result["indicators"]["pivots"] = pivots

    # Volatility and Sharpe Ratio
    returns, daily_vol, annual_vol = annualized_volatility(df["Close"])
    if len(returns) > 0:
        annual_volatility = annual_vol * 100
        annual_mean_return = returns.mean() * 252 * 100
        if daily_vol > 0:
            sharpe_ratio = (returns.mean() * 252) / annual_vol
        else:
            sharpe_ratio = 0.0

        result["risk_metrics"] = {
            "volatility_annualized_pct": round(annual_volatility, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "mean_return_annualized_pct": round(annual_mean_return, 2),
        }

    if include_earnings:
        result["earnings"] = get_earnings_data(symbol)

    return result


def compute_multi_symbol(
    symbols: list[str],
    period: str = "3mo",
    indicators: list[str] | None = None,
    include_earnings: bool = False,
    completed_sessions: bool = False,
) -> dict:
    """Compute indicators for multiple symbols."""
    results = []
    for symbol in symbols:
        result = compute_indicators(
            symbol, period, indicators, include_earnings, completed_sessions
        )
        results.append(result)

    return {"results": results}


# RSI needs ~14 bars, MACD's signal line needs ~26+9. Below these thresholds
# compute_raw_indicators still returns a number (it doesn't withhold output),
# so intraday_technicals.py surfaces this warning instead of a bare null-check.
MIN_BARS_FOR_RSI = 15
MIN_BARS_FOR_MACD = 35


def intraday_bar_warnings(n_bars: int) -> list[str]:
    """Return human-readable caveats when too few intraday bars exist for stable indicators.

    Empty list means RSI/MACD/ADX on this many bars are as trustworthy as they get.
    """
    if n_bars < MIN_BARS_FOR_RSI:
        return [
            f"Only {n_bars} bars available — RSI/ADX not yet reliable "
            f"(need {MIN_BARS_FOR_RSI}+, session likely just opened). "
            "Lean on price/flow/news instead."
        ]
    if n_bars < MIN_BARS_FOR_MACD:
        return [
            f"Only {n_bars} bars available — MACD signal line not yet reliable "
            f"(need {MIN_BARS_FOR_MACD}+). RSI/ADX are usable."
        ]
    return []


def interval_minutes(interval: str) -> int | None:
    """Minutes per bar for a yfinance intraday interval ("5m" -> 5, "1h" -> 60).

    Returns None for daily-or-longer or unrecognised intervals.
    """
    unit, value = interval[-1:], interval[:-1]
    if not value.isdigit():
        return None
    if unit == "m":
        return int(value)
    if unit == "h":
        return int(value) * 60
    return None

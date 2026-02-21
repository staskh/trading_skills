# ABOUTME: Computes technical indicators using pandas-ta.
# ABOUTME: Supports multi-symbol analysis and earnings data.

import pandas as pd
import pandas_ta as ta
import yfinance as yf

from trading_skills.earnings import get_next_earnings_date
from trading_skills.utils import annualized_volatility


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
        "adx": None,
        "dmp": None,
        "dmn": None,
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

    # MACD
    macd = ta.macd(close)
    if macd is not None and len(macd) > 0:
        line = macd.iloc[-1, 0]
        signal = macd.iloc[-1, 1]
        hist = macd.iloc[-1, 2]
        if pd.notna(line):
            result["macd_line"] = float(line)
        if pd.notna(signal):
            result["macd_signal"] = float(signal)
        if pd.notna(hist):
            result["macd_hist"] = float(hist)
        if len(macd) > 1:
            prev = macd.iloc[-2, 2]
            if pd.notna(prev):
                result["prev_macd_hist"] = float(prev)

    # ADX
    if "High" in df.columns and "Low" in df.columns:
        adx = ta.adx(df["High"], df["Low"], close, length=14)
        if adx is not None and len(adx) > 0:
            adx_val = adx.iloc[-1, 0]
            dmp_val = adx.iloc[-1, 1]
            dmn_val = adx.iloc[-1, 2]
            if pd.notna(adx_val):
                result["adx"] = float(adx_val)
            if pd.notna(dmp_val):
                result["dmp"] = float(dmp_val)
            if pd.notna(dmn_val):
                result["dmn"] = float(dmn_val)

    return result


def compute_indicators(
    symbol: str,
    period: str = "3mo",
    indicators: list[str] | None = None,
    include_earnings: bool = False,
) -> dict:
    """Compute technical indicators for a symbol."""
    if indicators is None:
        indicators = ["rsi", "macd", "bb", "sma", "ema", "atr", "adx"]

    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period)

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
) -> dict:
    """Compute indicators for multiple symbols."""
    results = []
    for symbol in symbols:
        result = compute_indicators(symbol, period, indicators, include_earnings)
        results.append(result)

    return {"results": results}

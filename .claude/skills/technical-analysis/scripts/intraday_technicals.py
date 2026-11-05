#!/usr/bin/env python3
# ABOUTME: CLI wrapper for intraday (sub-daily) technical indicator computation.
# ABOUTME: Same RSI/MACD/ADX-DMI math as technicals.py, run on 5m/15m/etc bars instead of daily.

import argparse
import json

import pandas as pd
import yfinance as yf

from trading_skills.technicals import (
    compute_raw_indicators,
    interval_minutes,
    intraday_bar_warnings,
)
from trading_skills.utils import generated_at_str


def _round(value, digits):
    return round(value, digits) if value is not None else None


def _crossover(raw_cross: dict | None, interval: str) -> dict | None:
    """Re-express the shared crossover helper's age in bars and minutes.

    detect_ema_crossover counts bars but names the field "days_ago", which is
    only true on daily bars — on 5m bars "days_ago": 4 means 20 minutes.
    """
    if raw_cross is None:
        return None
    bars_ago = raw_cross["days_ago"]
    minutes = interval_minutes(interval)
    return {
        "direction": raw_cross["direction"],
        "bars_ago": bars_ago,
        "minutes_ago": bars_ago * minutes if minutes is not None else None,
    }


def build_result(symbol: str, interval: str, period: str, df: pd.DataFrame) -> dict:
    """Compute the intraday indicator payload from an OHLCV frame."""
    df = df.dropna(subset=["Close"])
    result = {
        "symbol": symbol,
        "interval": interval,
        "period": period,
        "bars": len(df),
    }

    if df.empty:
        result["error"] = "No intraday data returned (market likely closed)"
        return result

    first_close = float(df["Close"].iloc[0])
    last_close = float(df["Close"].iloc[-1])
    result["price"] = {
        "current": round(last_close, 2),
        "change": round(last_close - first_close, 2),
        "change_pct": round((last_close / first_close - 1) * 100, 2),
    }

    result["warnings"] = intraday_bar_warnings(len(df))

    raw = compute_raw_indicators(df)
    result["indicators"] = {
        "rsi": _round(raw["rsi"], 2),
        "macd": {
            "macd": _round(raw["macd_line"], 4),
            "signal": _round(raw["macd_signal"], 4),
            "histogram": _round(raw["macd_hist"], 4),
            "prev_histogram": _round(raw["prev_macd_hist"], 4),
        },
        "ema": {
            "ema9": _round(raw["ema9"], 2),
            "ema21": _round(raw["ema21"], 2),
            "crossover": _crossover(raw["ema_crossover"], interval),
        },
        "adx": {
            "adx": _round(raw["adx"], 2),
            "dmp": _round(raw["dmp"], 2),
            "dmn": _round(raw["dmn"], 2),
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compute RSI/MACD/ADX-DMI on intraday bars (for same-day/next-day monitoring)"
    )
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument(
        "--interval", default="5m", help="Bar size: 1m,2m,5m,15m,30m,60m (default: 5m)"
    )
    parser.add_argument(
        "--period", default="1d", help="Lookback window: 1d,5d (default: 1d — today's session only)"
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()
    df = yf.Ticker(symbol).history(period=args.period, interval=args.interval)
    result = build_result(symbol, args.interval, args.period, df)
    result["generated_at"] = generated_at_str()
    result["data_delay"] = "15min"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

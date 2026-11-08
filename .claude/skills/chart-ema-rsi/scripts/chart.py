#!/usr/bin/env python3
# ABOUTME: CLI that renders a daily candle chart with EMA crossovers and RSI to a JPG.
# ABOUTME: Prints JSON with the image path, latest EMA/RSI values and the crossovers plotted.

import argparse
import json

from trading_skills.chart_ema_rsi import PERIOD_DAYS, render_chart


def main():
    parser = argparse.ArgumentParser(description="Daily candles with EMA crossovers and RSI")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--period", default="6mo", choices=sorted(PERIOD_DAYS))
    parser.add_argument("--fast", type=int, default=9, help="Fast EMA length")
    parser.add_argument("--slow", type=int, default=20, help="Slow EMA length")
    parser.add_argument("--rsi", type=int, default=14, help="RSI length")
    parser.add_argument("--output", help="JPG path (default sandbox/<SYMBOL>_ema_rsi_<time>.jpg)")
    args = parser.parse_args()

    result = render_chart(args.symbol, args.period, args.fast, args.slow, args.rsi, args.output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

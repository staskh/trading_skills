#!/usr/bin/env python3
# ABOUTME: CLI wrapper for technical indicator computation.
# ABOUTME: Supports multi-symbol analysis and earnings data.

import argparse
import json

from trading_skills.technicals import compute_indicators, compute_multi_symbol


def main():
    parser = argparse.ArgumentParser(description="Compute technical indicators")
    parser.add_argument("symbol", help="Ticker symbol (comma-separated for multiple)")
    parser.add_argument("--period", default="3mo", help="Historical period")
    parser.add_argument("--indicators", default=None, help="Comma-separated indicators")
    parser.add_argument("--earnings", action="store_true", help="Include earnings data")

    args = parser.parse_args()
    indicators = args.indicators.split(",") if args.indicators else None

    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbol.split(",")]

    if len(symbols) == 1:
        result = compute_indicators(symbols[0], args.period, indicators, args.earnings)
    else:
        result = compute_multi_symbol(symbols, args.period, indicators, args.earnings)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

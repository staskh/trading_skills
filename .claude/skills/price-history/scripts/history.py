#!/usr/bin/env python3
# ABOUTME: CLI wrapper for historical price data fetching.
# ABOUTME: Returns OHLCV data for specified period and interval.

import argparse
import json

from trading_skills.history import get_history


def main():
    parser = argparse.ArgumentParser(description="Fetch historical price data")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--period", default="1mo",
                       help="Period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max")
    parser.add_argument("--interval", default="1d",
                       help="Interval: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo")

    args = parser.parse_args()
    result = get_history(args.symbol.upper(), args.period, args.interval)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

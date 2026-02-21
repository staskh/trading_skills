#!/usr/bin/env python3
# ABOUTME: CLI wrapper for fundamental financial data fetching.
# ABOUTME: Returns financials, earnings, and key company metrics.

import argparse
import json

from trading_skills.fundamentals import get_fundamentals


def main():
    parser = argparse.ArgumentParser(description="Fetch fundamental data")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--type", default="all", choices=["all", "info", "financials", "earnings"],
                       help="Data type to fetch")

    args = parser.parse_args()
    result = get_fundamentals(args.symbol.upper(), args.type)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

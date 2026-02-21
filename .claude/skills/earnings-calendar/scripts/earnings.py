#!/usr/bin/env python3
# ABOUTME: CLI wrapper for earnings date retrieval.
# ABOUTME: Returns date, before/after market timing, and EPS estimate.

import argparse
import json

from trading_skills.earnings import get_earnings_info, get_multiple_earnings


def main():
    parser = argparse.ArgumentParser(description="Get upcoming earnings dates")
    parser.add_argument("symbols", help="Ticker symbol(s), comma-separated for multiple")

    args = parser.parse_args()

    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    if len(symbols) == 1:
        result = get_earnings_info(symbols[0])
    else:
        result = get_multiple_earnings(symbols)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

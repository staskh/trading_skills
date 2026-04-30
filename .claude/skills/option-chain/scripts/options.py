#!/usr/bin/env python3
# ABOUTME: CLI wrapper for option chain data fetching.
# ABOUTME: Supports listing expiries and fetching chains by date.

import argparse
import json
import sys

from trading_skills.options import get_expiries, get_option_chain
from trading_skills.utils import generated_at_str


def main():
    parser = argparse.ArgumentParser(description="Fetch option data from Yahoo Finance")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--expiries", action="store_true", help="List expiration dates only")
    parser.add_argument("--expiry", help="Fetch chain for specific expiry (YYYY-MM-DD)")

    args = parser.parse_args()
    symbol = args.symbol.upper()

    ga = generated_at_str()
    if args.expiries:
        expiries = get_expiries(symbol)
        if not expiries:
            print(json.dumps({"error": f"No options found for {symbol}"}))
            sys.exit(1)
        print(json.dumps({"symbol": symbol, "expiries": expiries, "generated_at": ga, "data_delay": "15min"}, indent=2))
    elif args.expiry:
        result = get_option_chain(symbol, args.expiry)
        result["generated_at"] = ga
        result["data_delay"] = "15min"
        print(json.dumps(result, indent=2))
    else:
        # Default: show expiries
        expiries = get_expiries(symbol)
        if not expiries:
            print(json.dumps({"error": f"No options found for {symbol}"}))
            sys.exit(1)
        print(json.dumps({"symbol": symbol, "expiries": expiries, "generated_at": ga, "data_delay": "15min"}, indent=2))


if __name__ == "__main__":
    main()

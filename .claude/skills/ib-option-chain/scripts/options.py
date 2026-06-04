#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IB option chain data fetching.
# ABOUTME: Supports listing expiries and fetching chains by date via IBKR.

import argparse
import asyncio
import json
import sys

from trading_skills.broker.options import get_expiries, get_option_chain
from trading_skills.utils import generated_at_str


def main():
    parser = argparse.ArgumentParser(description="Fetch option data from Interactive Brokers")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--expiries", action="store_true", help="List expiration dates only")
    parser.add_argument("--expiry", help="Fetch chain for specific expiry (YYYYMMDD)")
    parser.add_argument("--port", type=int, default=7496, help="IB port (7497=paper, 7496=live)")
    parser.add_argument(
        "--sec-type",
        dest="sec_type",
        choices=["stk", "fut"],
        default=None,
        help="Force asset type (stk/fut). Default: auto-detect from IB contract details.",
    )

    args = parser.parse_args()
    symbol = args.symbol.upper()

    ga = generated_at_str()
    if args.expiries:
        result = asyncio.run(get_expiries(symbol, port=args.port, sec_type=args.sec_type))
        if not result.get("success"):
            print(json.dumps(result))
            sys.exit(1)
        result["generated_at"] = ga
        result["data_delay"] = "real-time"
        print(json.dumps(result, indent=2))
    elif args.expiry:
        result = asyncio.run(
            get_option_chain(symbol, args.expiry, port=args.port, sec_type=args.sec_type)
        )
        if not result.get("success"):
            print(json.dumps(result))
            sys.exit(1)
        result["generated_at"] = ga
        result["data_delay"] = "real-time"
        print(json.dumps(result, indent=2))
    else:
        # Default: show expiries
        result = asyncio.run(get_expiries(symbol, port=args.port, sec_type=args.sec_type))
        if not result.get("success"):
            print(json.dumps(result))
            sys.exit(1)
        result["generated_at"] = ga
        result["data_delay"] = "real-time"
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

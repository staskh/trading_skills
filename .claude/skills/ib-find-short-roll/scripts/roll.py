#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IB short position roll finder.
# ABOUTME: Returns JSON with roll, spread, or covered call candidates from real-time IB data.

import argparse
import asyncio
import json

from trading_skills.broker.roll import find_roll_candidates


async def main():
    parser = argparse.ArgumentParser(description="Find roll options for short position")
    parser.add_argument("symbol", type=str, help="Ticker symbol (e.g., GOOG)")
    parser.add_argument("--strike", type=float, default=None, help="Current short strike")
    parser.add_argument("--expiry", type=str, default=None, help="Current expiry (YYYYMMDD)")
    parser.add_argument("--right", type=str, default="C", choices=["C", "P"], help="Call or Put")
    parser.add_argument("--port", type=int, default=7496, help="IB port")
    parser.add_argument("--account", type=str, default=None, help="Account ID")

    args = parser.parse_args()

    result = await find_roll_candidates(
        symbol=args.symbol,
        port=args.port,
        account=args.account,
        strike=args.strike,
        expiry=args.expiry,
        right=args.right,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

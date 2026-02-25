#!/usr/bin/env python3
# ABOUTME: CLI wrapper for tactical collar strategy analysis.
# ABOUTME: Returns JSON with collar scenarios and recommendations for PMCC positions.

import argparse
import asyncio
import json

from trading_skills.broker.collar import find_collar_candidates


async def main():
    parser = argparse.ArgumentParser(description="Generate tactical collar analysis")
    parser.add_argument("symbol", help="Stock symbol to analyze")
    parser.add_argument("--port", type=int, default=7496, help="IB port (default: 7496)")
    parser.add_argument("--account", type=str, default=None, help="IB account ID")

    args = parser.parse_args()

    result = await find_collar_candidates(
        symbol=args.symbol,
        port=args.port,
        account=args.account,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

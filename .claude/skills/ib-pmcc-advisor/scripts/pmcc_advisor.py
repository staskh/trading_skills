#!/usr/bin/env python3
# ABOUTME: CLI entry point for IB PMCC Advisor.
# ABOUTME: Connects to IB, analyzes diagonal spread positions, returns JSON analysis.

import argparse
import asyncio
import json
import sys

from trading_skills.broker.pmcc_advisor import get_pmcc_data


async def main():
    parser = argparse.ArgumentParser(description="Analyze PMCC (diagonal spread) positions from IB")
    parser.add_argument("--port", type=int, default=7496, help="IB port (7496=live, 7497=paper)")
    parser.add_argument("--account", type=str, default=None, help="Specific account ID")
    parser.add_argument(
        "--min-roll-dte",
        type=int,
        default=7,
        dest="min_roll_dte",
        help="Minimum DTE for roll candidates (default: 7)",
    )
    parser.add_argument(
        "--price-mode",
        type=str,
        default="mid",
        choices=["mid", "last"],
        dest="price_mode",
        help="Option pricing mode: mid (default) or last",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Analyze only these symbols (e.g. --symbols NVDA WMT)",
    )

    args = parser.parse_args()

    print("Connecting to IB...", file=sys.stderr)
    result = await get_pmcc_data(
        port=args.port,
        account=args.account,
        min_roll_dte=args.min_roll_dte,
        price_mode=args.price_mode,
        symbols=args.symbols,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

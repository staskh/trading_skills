#!/usr/bin/env python3
# ABOUTME: CLI wrapper for portfolio action report generation.
# ABOUTME: Connects to IB, analyzes positions, returns JSON with risk assessment.

import argparse
import asyncio
import json
import sys

from trading_skills.broker.portfolio_action import (
    analyze_portfolio,
    get_portfolio_data,
)


async def main():
    parser = argparse.ArgumentParser(description="Generate portfolio action report")
    parser.add_argument("--port", type=int, default=7497, help="IB port (7497=paper, 7496=live)")
    parser.add_argument("--account", type=str, default=None, help="Specific account ID")

    args = parser.parse_args()

    # Fetch portfolio data
    print("Connecting to IB...", file=sys.stderr)
    data = await get_portfolio_data(args.port, args.account)

    if "error" in data:
        print(json.dumps({"error": data["error"]}))
        return

    # Analyze portfolio
    print("Analyzing portfolio...", file=sys.stderr)
    analysis = analyze_portfolio(data)

    print(json.dumps(analysis, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

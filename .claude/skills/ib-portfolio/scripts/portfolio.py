#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IB portfolio position fetching.
# ABOUTME: Requires TWS or IB Gateway running locally.

import argparse
import asyncio
import json

from trading_skills.broker.portfolio import get_portfolio


def main():
    parser = argparse.ArgumentParser(description="Fetch IB portfolio")
    parser.add_argument("--port", type=int, default=7497, help="IB port (7497=paper, 7496=live)")
    parser.add_argument("--account", type=str, default=None, help="IB account ID (e.g., U790497)")
    parser.add_argument("--all", action="store_true", help="Fetch positions from all accounts")

    args = parser.parse_args()
    result = asyncio.run(get_portfolio(args.port, args.account, args.all))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

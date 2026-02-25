#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IB account summary fetching.
# ABOUTME: Requires TWS or IB Gateway running locally.

import argparse
import asyncio
import json

from trading_skills.broker.account import get_account_summary


def main():
    parser = argparse.ArgumentParser(description="Fetch IB account summary")
    parser.add_argument("--port", type=int, default=7496, help="IB port (7496=live, 7497=paper)")

    args = parser.parse_args()
    result = asyncio.run(get_account_summary(args.port))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

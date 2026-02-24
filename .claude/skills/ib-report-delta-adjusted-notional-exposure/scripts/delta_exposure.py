#!/usr/bin/env python3
# ABOUTME: CLI wrapper for delta-adjusted notional exposure reporting.
# ABOUTME: Returns JSON with option deltas calculated via Black-Scholes across all IBKR accounts.

import argparse
import asyncio
import json

from trading_skills.broker.delta_exposure import get_delta_exposure


def main():
    parser = argparse.ArgumentParser(description="Calculate delta-adjusted notional exposure")
    parser.add_argument("--port", type=int, default=7496, help="IB port (7496=live, 7497=paper)")

    args = parser.parse_args()
    result = asyncio.run(get_delta_exposure(args.port))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

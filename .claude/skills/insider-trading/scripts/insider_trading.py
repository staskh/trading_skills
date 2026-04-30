#!/usr/bin/env python3
# ABOUTME: CLI wrapper for insider trading data fetching.
# ABOUTME: Returns insider transactions and net sentiment for one or more symbols.

import argparse
import json

from trading_skills.insider_trading import (
    get_insider_transactions,
    get_multiple_insider_transactions,
)
from trading_skills.utils import generated_at_str


def main():
    parser = argparse.ArgumentParser(description="Fetch insider trading data")
    parser.add_argument("symbols", help="Ticker symbol or comma-separated list")
    parser.add_argument("--days", type=int, default=90, help="Trailing days to look back")

    args = parser.parse_args()
    symbol_list = [s.strip().upper() for s in args.symbols.split(",")]

    if len(symbol_list) == 1:
        result = get_insider_transactions(symbol_list[0], args.days)
    else:
        result = get_multiple_insider_transactions(symbol_list, args.days)

    result["generated_at"] = generated_at_str()
    result["data_delay"] = "EOD"
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

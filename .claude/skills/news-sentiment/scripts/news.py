#!/usr/bin/env python3
# ABOUTME: CLI wrapper for stock news fetching.
# ABOUTME: Returns headlines, publishers, and dates.

import argparse
import json

from trading_skills.news import get_news


def main():
    parser = argparse.ArgumentParser(description="Fetch stock news")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--limit", type=int, default=10, help="Number of articles")

    args = parser.parse_args()
    result = get_news(args.symbol.upper(), args.limit)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

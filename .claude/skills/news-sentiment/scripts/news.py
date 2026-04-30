#!/usr/bin/env python3
# ABOUTME: CLI wrapper for stock news fetching.
# ABOUTME: Returns headlines, publishers, and dates.

import argparse
import json

from trading_skills.news import get_news
from trading_skills.utils import generated_at_str


def main():
    parser = argparse.ArgumentParser(description="Fetch stock news")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--limit", type=int, default=10, help="Number of articles")

    args = parser.parse_args()
    result = get_news(args.symbol.upper(), args.limit)
    result["generated_at"] = generated_at_str()
    result["data_delay"] = "15min"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

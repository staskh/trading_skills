#!/usr/bin/env python3
# ABOUTME: CLI wrapper for stock quote fetching.
# ABOUTME: Outputs JSON with price, volume, and key metrics.

import json
import sys

from trading_skills.quote import get_quote
from trading_skills.utils import generated_at_str


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: quote.py SYMBOL"}))
        sys.exit(1)

    symbol = sys.argv[1].upper()
    result = get_quote(symbol)
    result["generated_at"] = generated_at_str()
    result["data_delay"] = "15min"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

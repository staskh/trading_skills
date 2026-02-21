#!/usr/bin/env python3
# ABOUTME: CLI wrapper for comprehensive stock analysis data gathering.
# ABOUTME: Returns detailed JSON for PDF generation by Claude.

import argparse
import json
import sys

from trading_skills.report import generate_report_data


def main():
    parser = argparse.ArgumentParser(description="Gather stock analysis data")
    parser.add_argument("symbol", help="Stock ticker symbol")
    args = parser.parse_args()

    symbol = args.symbol.upper()
    result = generate_report_data(symbol)

    if "error" in result:
        print(json.dumps(result))
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

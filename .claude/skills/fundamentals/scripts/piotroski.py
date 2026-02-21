#!/usr/bin/env python3
# ABOUTME: CLI wrapper for Piotroski F-Score calculation.
# ABOUTME: Returns a score from 0-9 based on 9 fundamental criteria.

import argparse
import json

from trading_skills.piotroski import calculate_piotroski_score


def main():
    parser = argparse.ArgumentParser(description="Calculate Piotroski F-Score")
    parser.add_argument("symbol", help="Ticker symbol")

    args = parser.parse_args()
    result = calculate_piotroski_score(args.symbol.upper())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# ABOUTME: CLI wrapper for price correlation computation.
# ABOUTME: Use for portfolio diversification analysis and pair trading.

import argparse
import json

from trading_skills.correlation import compute_correlation


def main():
    parser = argparse.ArgumentParser(description="Compute price correlation matrix")
    parser.add_argument("symbols", help="Comma-separated ticker symbols (min 2)")
    parser.add_argument("--period", default="3mo", help="Historical period (default: 3mo)")

    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    result = compute_correlation(symbols, args.period)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

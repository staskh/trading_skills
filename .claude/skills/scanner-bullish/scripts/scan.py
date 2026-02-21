#!/usr/bin/env python3
# ABOUTME: CLI wrapper for bullish trend scanning.
# ABOUTME: Ranks symbols by composite bullish score.

import argparse
import json
import sys

import pandas as pd

from trading_skills.scanner_bullish import compute_bullish_score, scan_symbols


def main():
    parser = argparse.ArgumentParser(description="Scan for bullish trends")
    parser.add_argument("symbols", help="Comma-separated ticker symbols")
    parser.add_argument("--top", type=int, default=30, help="Number of top symbols to return (default: 30)")
    parser.add_argument("--period", default="3mo", help="Historical period: 1mo, 3mo, 6mo (default: 3mo)")

    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if not symbols:
        print("Error: No symbols provided", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing {len(symbols)} symbols...", file=sys.stderr)

    top_results = scan_symbols(symbols, args.top, args.period)

    output = {
        "scan_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "symbols_scanned": len(symbols),
        "top_count": len(top_results),
        "results": top_results,
    }

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

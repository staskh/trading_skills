#!/usr/bin/env python3
# ABOUTME: CLI wrapper for PMCC suitability scanning.
# ABOUTME: Scores on delta accuracy, liquidity, spread tightness, IV level, and yield.

import argparse
import json
import sys
from datetime import datetime

from trading_skills.scanner_pmcc import analyze_pmcc


def main():
    parser = argparse.ArgumentParser(description="PMCC scanner")
    parser.add_argument("symbols", help="Comma-separated symbols or JSON file path")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--min-leaps-days", type=int, default=270, help="Minimum LEAPS days (default: 270)")
    parser.add_argument("--leaps-delta", type=float, default=0.80, help="Target LEAPS delta (default: 0.80)")
    parser.add_argument("--short-delta", type=float, default=0.20, help="Target short call delta (default: 0.20)")

    args = parser.parse_args()

    # Parse symbols
    if args.symbols.endswith(".json"):
        with open(args.symbols) as f:
            data = json.load(f)
            symbols = [r["symbol"] for r in data.get("results", [])]
    else:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    if not symbols:
        print("Error: No symbols provided", file=sys.stderr)
        sys.exit(1)

    print(f"Analyzing {len(symbols)} symbols for PMCC (LEAPS >= {args.min_leaps_days} days, delta={args.leaps_delta}, short delta={args.short_delta})...", file=sys.stderr)

    results = []
    for i, symbol in enumerate(symbols, 1):
        print(f"  [{i}/{len(symbols)}] {symbol}...", file=sys.stderr)
        result = analyze_pmcc(symbol, min_leaps_days=args.min_leaps_days, leaps_delta=args.leaps_delta, short_delta=args.short_delta)
        if result:
            results.append(result)

    valid_results = [r for r in results if "pmcc_score" in r]
    valid_results.sort(key=lambda x: (x["pmcc_score"], x["metrics"]["annual_yield_est_pct"]), reverse=True)

    output = {
        "scan_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "criteria": {
            "leaps_min_days": args.min_leaps_days,
            "leaps_target_delta": args.leaps_delta,
            "short_days_range": "7-21",
            "short_target_delta": args.short_delta,
            "short_strike": "above LEAPS strike"
        },
        "count": len(valid_results),
        "results": valid_results,
        "errors": [r for r in results if "error" in r],
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Results saved to {args.output}", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

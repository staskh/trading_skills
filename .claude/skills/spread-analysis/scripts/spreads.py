#!/usr/bin/env python3
# ABOUTME: CLI wrapper for option spread strategy analysis.
# ABOUTME: Supports verticals, diagonals, straddles, strangles, iron condors.

import argparse
import json

from trading_skills.spreads import (
    analyze_diagonal,
    analyze_iron_condor,
    analyze_straddle,
    analyze_strangle,
    analyze_vertical,
)


def main():
    parser = argparse.ArgumentParser(description="Analyze option spreads")
    parser.add_argument("symbol", help="Ticker symbol")
    parser.add_argument("--strategy", required=True,
                       choices=["vertical", "diagonal", "straddle", "strangle", "iron-condor"])
    parser.add_argument("--expiry", help="Expiry date (YYYY-MM-DD)")
    parser.add_argument("--long-expiry", help="Long leg expiry for diagonal")
    parser.add_argument("--short-expiry", help="Short leg expiry for diagonal")
    parser.add_argument("--type", choices=["call", "put"], help="For vertical spread")
    parser.add_argument("--strike", type=float, help="Strike for straddle")
    parser.add_argument("--long-strike", type=float, help="Long strike for vertical")
    parser.add_argument("--short-strike", type=float, help="Short strike for vertical")
    parser.add_argument("--put-strike", type=float, help="Put strike for strangle")
    parser.add_argument("--call-strike", type=float, help="Call strike for strangle")
    parser.add_argument("--put-long", type=float, help="Long put for iron condor")
    parser.add_argument("--put-short", type=float, help="Short put for iron condor")
    parser.add_argument("--call-short", type=float, help="Short call for iron condor")
    parser.add_argument("--call-long", type=float, help="Long call for iron condor")

    args = parser.parse_args()

    if args.strategy == "vertical":
        result = analyze_vertical(args.symbol, args.expiry, args.type,
                                  args.long_strike, args.short_strike)
    elif args.strategy == "diagonal":
        result = analyze_diagonal(
            args.symbol, args.type,
            args.long_expiry, args.long_strike,
            args.short_expiry, args.short_strike
        )
    elif args.strategy == "straddle":
        result = analyze_straddle(args.symbol, args.expiry, args.strike)
    elif args.strategy == "strangle":
        result = analyze_strangle(args.symbol, args.expiry, args.put_strike, args.call_strike)
    elif args.strategy == "iron-condor":
        result = analyze_iron_condor(args.symbol, args.expiry, args.put_long,
                                     args.put_short, args.call_short, args.call_long)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

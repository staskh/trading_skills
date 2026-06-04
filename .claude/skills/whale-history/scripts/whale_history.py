#!/usr/bin/env python3
# ABOUTME: CLI for historical options whale detection over Massive OPRA day-agg flatfiles.
# ABOUTME: Wraps hunt_history() and outputs JSON; writes a copy to --out when given.

import argparse
import json
import sys
from datetime import date, timedelta

from trading_skills.massive.whale_history import FlatfileConfigError, hunt_history
from trading_skills.utils import generated_at_str, latest_trading_date


def main():
    parser = argparse.ArgumentParser(description="Hunt historical option whales via OPRA flatfiles")
    parser.add_argument("symbol", help="Underlying ticker (e.g. SPY)")
    parser.add_argument("--start", default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD (default: latest session)")
    parser.add_argument(
        "--months", type=int, default=2, help="Lookback months when --start omitted (default: 2)"
    )
    parser.add_argument(
        "--sigma-z", type=float, default=3.5, dest="sigma_z", help="Modified z threshold (3.5)"
    )
    parser.add_argument(
        "--floor", type=float, default=500_000.0, help="Min $ invested to qualify (default 500k)"
    )
    parser.add_argument(
        "--exclude-0dte", action="store_true", help="Drop contracts expiring on the trade date"
    )
    parser.add_argument("--out", default=None, help="Also write JSON to this path")
    args = parser.parse_args()

    end = date.fromisoformat(args.end) if args.end else latest_trading_date()
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        # approx N months back (30 days/month is fine — list_trading_days bounds it)
        start = end - timedelta(days=args.months * 31)

    print(f"Hunting {args.symbol.upper()} whales {start}..{end}...", file=sys.stderr)

    try:
        result = hunt_history(
            args.symbol,
            start=start,
            end=end,
            sigma_z=args.sigma_z,
            floor=args.floor,
            exclude_0dte=args.exclude_0dte,
        )
    except FlatfileConfigError as exc:
        print(
            json.dumps(
                {
                    "underlying": args.symbol.upper(),
                    "error": str(exc),
                    "generated_at": generated_at_str(),
                    "data_delay": "stalled - using yesterday's data",
                },
                indent=2,
            )
        )
        sys.exit(1)

    result["generated_at"] = generated_at_str()
    result["data_delay"] = "end-of-day (T+1 finalized flatfiles)"
    out_json = json.dumps(result, indent=2, default=str)

    if args.out:
        with open(args.out, "w") as f:
            f.write(out_json)
        print(f"wrote {args.out}", file=sys.stderr)
    print(out_json)


if __name__ == "__main__":
    main()

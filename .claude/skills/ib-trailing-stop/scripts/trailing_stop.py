#!/usr/bin/env python3
# ABOUTME: CLI entry point for IB Trailing Stop manager.
# ABOUTME: Connects to IB, analyzes stock + naked LEAPS positions, places native TRAIL orders.

import argparse
import asyncio
import json
import sys

from trading_skills.broker.trailing_stop import get_trailing_stop_data


async def main():
    parser = argparse.ArgumentParser(
        description="Manage native TRAIL orders for stocks and naked LEAPS (PMCC excluded)"
    )
    parser.add_argument("--port", type=int, default=7496, help="IB port (7496=live, 7497=paper)")
    parser.add_argument("--account", type=str, default=None, help="Specific account ID")
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Analyze only these symbols (e.g. --symbols JOBY)",
    )
    trail_group = parser.add_mutually_exclusive_group()
    trail_group.add_argument(
        "--trail-pct",
        type=float,
        default=None,
        dest="trail_pct",
        help="Trail amount as %% of reference price (default: 20 unless --trail-amt set)",
    )
    trail_group.add_argument(
        "--trail-amt",
        type=float,
        default=None,
        dest="trail_amt",
        help="Trail amount in dollars (mutually exclusive with --trail-pct)",
    )
    parser.add_argument(
        "--price-mode",
        type=str,
        default="mid",
        choices=["mid", "last"],
        dest="price_mode",
        help="Option pricing mode for LEAPS: mid (default) or last",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Cancel orphans and place TS_ TRAIL orders (default: dry-run)",
    )
    parser.add_argument(
        "--forced",
        action="store_true",
        default=False,
        help="Cancel and replace existing TS_ orders with current parameters; requires --execute",
    )

    args = parser.parse_args()

    # Default trail_pct=20 only when neither flag was supplied
    trail_pct = args.trail_pct
    trail_amt = args.trail_amt
    if trail_pct is None and trail_amt is None:
        trail_pct = 20.0

    dry_run = not args.execute
    if args.forced and dry_run:
        print(
            "Warning: dry-run will preview forced replacement, but no orders are submitted unless --execute is added.",
            file=sys.stderr,
        )

    if dry_run:
        mode = "DRY RUN"
    elif args.forced:
        mode = "EXECUTE (forced — replace existing TS_ orders)"
    else:
        mode = "EXECUTE"
    print(f"[{mode}] Connecting to IB on port {args.port}...", file=sys.stderr)

    result = await get_trailing_stop_data(
        port=args.port,
        account=args.account,
        symbols=args.symbols,
        trail_pct=trail_pct,
        trail_amt=trail_amt,
        price_mode=args.price_mode,
        dry_run=dry_run,
        forced=args.forced,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

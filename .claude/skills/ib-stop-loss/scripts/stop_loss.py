#!/usr/bin/env python3
# ABOUTME: CLI entry point for IB Stop-Loss manager.
# ABOUTME: Connects to IB, analyzes PMCC positions, sets conditional stop-loss orders.

import argparse
import asyncio
import json
import sys

from trading_skills.broker.stop_loss import get_stop_loss_data


async def main():
    parser = argparse.ArgumentParser(
        description="Manage stop-loss conditional orders for PMCC positions in IB"
    )
    parser.add_argument("--port", type=int, default=7496, help="IB port (7496=live, 7497=paper)")
    parser.add_argument("--account", type=str, default=None, help="Specific account ID")
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Analyze only these symbols (e.g. --symbols NVDA WMT)",
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=50.0,
        dest="stop_pct",
        help="LEAPS loss %% that triggers exit (default: 50)",
    )
    parser.add_argument(
        "--short-near-strike-pct",
        type=float,
        default=5.0,
        dest="short_near_strike_pct",
        help="Alert when spot is within this %% of (or above) the short strike (default: 5)",
    )
    parser.add_argument(
        "--price-mode",
        type=str,
        default="mid",
        choices=["mid", "last"],
        dest="price_mode",
        help="Option pricing mode: mid (default) or last",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Connect live and run full analysis (default: dry-run only)",
    )
    parser.add_argument(
        "--set-orders",
        action="store_true",
        default=False,
        dest="set_orders",
        help="Submit conditional stop-loss orders to IB (requires --execute)",
    )
    parser.add_argument(
        "--forced",
        action="store_true",
        default=False,
        help="Overwrite existing watermarks even if new watermark is lower (requires --set-orders)",
    )

    args = parser.parse_args()

    dry_run = not args.execute
    if args.set_orders and dry_run:
        print(
            "Warning: --set-orders has no effect in dry-run mode. Add --execute to submit orders.",
            file=sys.stderr,
        )
    if args.forced and not args.set_orders:
        print(
            "Warning: --forced has no effect without --set-orders.",
            file=sys.stderr,
        )

    if dry_run:
        mode = "DRY RUN"
    elif args.set_orders:
        mode = "EXECUTE + SET ORDERS (FORCED)" if args.forced else "EXECUTE + SET ORDERS"
    else:
        mode = "EXECUTE (analysis only)"
    print(f"[{mode}] Connecting to IB on port {args.port}...", file=sys.stderr)

    result = await get_stop_loss_data(
        port=args.port,
        account=args.account,
        symbols=args.symbols,
        stop_pct=args.stop_pct,
        short_near_strike_pct=args.short_near_strike_pct,
        price_mode=args.price_mode,
        dry_run=dry_run,
        set_orders=args.set_orders,
        forced=args.forced,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

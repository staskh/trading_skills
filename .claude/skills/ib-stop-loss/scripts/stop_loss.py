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
        help="Submit conditional orders to IB (default: dry-run only)",
    )
    parser.add_argument(
        "--forced",
        action="store_true",
        default=False,
        help="Overwrite existing watermarks even if new watermark is lower (requires --execute)",
    )
    parser.add_argument(
        "--alerts-only",
        action="store_true",
        default=False,
        dest="alerts_only",
        help="Report alerts only — skip watermark/stop-price computation and order proposals",
    )

    args = parser.parse_args()

    dry_run = not args.execute
    if args.forced and dry_run:
        print(
            "Warning: --forced has no effect in dry-run mode. Add --execute to submit orders.",
            file=sys.stderr,
        )
    if args.alerts_only and args.execute:
        print(
            "Warning: --alerts-only disables order submission. --execute ignored.",
            file=sys.stderr,
        )

    if args.alerts_only:
        mode = "ALERTS ONLY"
    elif dry_run:
        mode = "DRY RUN"
    else:
        mode = "EXECUTE FORCED" if args.forced else "EXECUTE"
    print(f"[{mode}] Connecting to IB on port {args.port}...", file=sys.stderr)

    result = await get_stop_loss_data(
        port=args.port,
        account=args.account,
        symbols=args.symbols,
        stop_pct=args.stop_pct,
        short_near_strike_pct=args.short_near_strike_pct,
        price_mode=args.price_mode,
        dry_run=dry_run or args.alerts_only,
        forced=args.forced,
        alerts_only=args.alerts_only,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

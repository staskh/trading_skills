#!/usr/bin/env python3
# ABOUTME: CLI entry point for IB Stop-Loss manager.
# ABOUTME: Connects to IB, analyzes PMCC/LEAPS/stock positions, sets conditional stop-loss orders.

import argparse
import asyncio
import json
import sys

from trading_skills.broker.stop_loss import get_stop_loss_data


def normalize_symbols(symbols: list[str] | None) -> list[str] | None:
    """Split comma-separated tokens so both '--symbols A B' and '--symbols A,B' work."""
    if symbols is None:
        return None
    result = [s.upper() for tok in symbols for s in tok.split(",") if s]
    return result or None


async def main():
    parser = argparse.ArgumentParser(
        description="Manage conditional stop-loss orders for PMCC, naked LEAPS, and stock positions"
    )
    parser.add_argument("--port", type=int, default=7497, help="IB port (7496=live, 7497=paper)")
    parser.add_argument("--account", type=str, default=None, help="Specific account ID")
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=None,
        help="Analyze only these symbols (e.g. --symbols NVDA WMT)",
    )
    parser.add_argument(
        "--legs",
        type=str,
        nargs="+",
        default=None,
        help=(
            "Filter to specific option legs: SYMBOL:STRIKE[C|P]:EXPIRY "
            "(e.g. --legs IBKR:70C:20270115 IBKR:100C:20260918). "
            "Right defaults to C. Takes precedence over --symbols."
        ),
    )
    parser.add_argument(
        "--stop-pct",
        type=float,
        default=40.0,
        dest="stop_pct",
        help="Loss %% that triggers exit (default: 40)",
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
        help="Cancel orphan orders and place SL_ conditional stop-loss orders (default: dry-run)",
    )
    parser.add_argument(
        "--forced",
        action="store_true",
        default=False,
        help="Use current_mid as basis (can lower existing stops); requires --execute",
    )

    args = parser.parse_args()

    dry_run = not args.execute
    if args.forced and dry_run:
        print(
            "Warning: --forced has no effect in dry-run mode. Add --execute to submit orders.",
            file=sys.stderr,
        )

    if dry_run:
        mode = "DRY RUN"
    elif args.forced:
        mode = "EXECUTE (forced — basis = current mid price)"
    else:
        mode = "EXECUTE"
    print(f"[{mode}] Connecting to IB on port {args.port}...", file=sys.stderr)

    result = await get_stop_loss_data(
        port=args.port,
        account=args.account,
        symbols=normalize_symbols(args.symbols),
        legs=args.legs,
        stop_pct=args.stop_pct,
        short_near_strike_pct=args.short_near_strike_pct,
        price_mode=args.price_mode,
        dry_run=dry_run,
        forced=args.forced,
    )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

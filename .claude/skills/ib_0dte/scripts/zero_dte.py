#!/usr/bin/env python3
# ABOUTME: CLI wrapper for the 0DTE credit-spread finder backed by IBKR data.
# ABOUTME: Finds best bear-call / bull-put / iron-condor trades within a budget.

import argparse
import asyncio
import json
import sys

from trading_skills.broker.zero_dte import (
    SPREAD_TYPES,
    find_0dte_spreads,
    get_0dte_expiries,
)
from trading_skills.utils import generated_at_str


def main():
    parser = argparse.ArgumentParser(
        description="Find best 0DTE credit spreads from Interactive Brokers"
    )
    parser.add_argument("symbol", help="Underlying symbol (e.g. SPX, NDX, RUT, VIX, AAPL, SPY)")
    parser.add_argument(
        "--type",
        dest="spread_type",
        choices=SPREAD_TYPES,
        default="bear_call",
        help="Spread type (default: bear_call)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=1000.0,
        help="Max capital at risk in dollars (default: 1000)",
    )
    parser.add_argument("--expiry", help="Expiry YYYYMMDD (default: today ET, i.e. true 0DTE)")
    parser.add_argument("--top", type=int, default=5, help="Number of candidates to return")
    parser.add_argument(
        "--min-pop",
        type=float,
        default=0.0,
        help="Minimum probability of profit filter, 0-1 (default: 0)",
    )
    parser.add_argument(
        "--max-width", type=float, default=None, help="Max strike width in dollars (optional)"
    )
    parser.add_argument(
        "--delta",
        type=float,
        default=None,
        help="Cap the |delta| of the short leg(s), e.g. 0.20 — a manual risk limit (optional)",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="If IBKR streams no live quotes/greeks (off-hours), price from yesterday's close "
        "and derive greeks via Black-Scholes (default: greeks only from IBKR, no stale marks)",
    )
    parser.add_argument(
        "--no-events",
        action="store_true",
        help="Skip the live economic-calendar lookup (falls back to static event guidance)",
    )
    parser.add_argument(
        "--account",
        help="IBKR account the trade will be committed to (default: sole managed account)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Place the chosen spread as a live combo order (default: dry run, propose only)",
    )
    parser.add_argument(
        "--pick",
        type=int,
        default=1,
        help="1-based rank of the candidate to execute (default: 1 = best)",
    )
    parser.add_argument(
        "--limit",
        type=float,
        default=None,
        help="Net credit limit price override (default: candidate's net credit)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="If a live order for this symbol/expiry/type already rests, cancel and re-place it "
        "(default: refuse as a duplicate)",
    )
    parser.add_argument(
        "--stop-mult",
        type=float,
        default=2.0,
        help="Premium-cap stop: close when the spread reaches this multiple of the credit "
        "(default: 2.0 = lose ~1x credit). 0 disables the premium cap.",
    )
    parser.add_argument(
        "--stop-buffer",
        type=float,
        default=0.0,
        help="Points before the short strike to trigger the level stop (default: 0 = at the strike)",
    )
    parser.add_argument(
        "--stop-delta",
        type=float,
        default=None,
        help="Also stop when the short-leg delta reaches this level (optional; e.g. 0.30)",
    )
    parser.add_argument(
        "--fill-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for the entry to fill before cancelling it (stops need a fill)",
    )
    parser.add_argument("--expiries", action="store_true", help="List available expiries and exit")
    parser.add_argument("--port", type=int, default=7497, help="IB port (7497=paper, 7496=live)")

    args = parser.parse_args()
    symbol = args.symbol.upper()
    ga = generated_at_str()

    if args.expiries:
        result = asyncio.run(get_0dte_expiries(symbol, port=args.port))
    else:
        result = asyncio.run(
            find_0dte_spreads(
                symbol,
                spread_type=args.spread_type,
                budget=args.budget,
                expiry=args.expiry,
                port=args.port,
                account=args.account,
                execute=args.execute,
                pick=args.pick,
                limit=args.limit,
                replace=args.replace,
                top=args.top,
                min_pop=args.min_pop,
                max_width=args.max_width,
                max_short_delta=args.delta,
                allow_stale=args.allow_stale,
                fetch_events=not args.no_events,
                stop_mult=args.stop_mult,
                stop_buffer=args.stop_buffer,
                stop_delta=args.stop_delta,
                fill_timeout=args.fill_timeout,
            )
        )

    result["generated_at"] = ga
    result.setdefault("data_delay", "real-time")  # broker sets this when it knows

    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()

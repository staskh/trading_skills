#!/usr/bin/env python3
# ABOUTME: CLI wrapper for the 0DTE credit-spread finder backed by IBKR data.
# ABOUTME: Finds best bear-call / bull-put / iron-condor trades within a budget.

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_skills.broker.zero_dte import (
    SPREAD_TYPES,
    find_0dte_spreads,
    get_0dte_expiries,
)
from trading_skills.broker.zero_dte_stop import verify_zdte_stops
from trading_skills.utils import generated_at_str

_NY = ZoneInfo("America/New_York")


def _normalize_time_exit(value):
    """Map None (use preset) through; treat 'none'/'off'/'' as disabled ('')."""
    if value is None:
        return None
    return "" if value.strip().lower() in ("none", "off", "") else value.strip()


def _sandbox_dir() -> Path:
    """Locate the repo's sandbox/ dir (walk up to pyproject.toml); create if missing."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            sb = parent / "sandbox"
            sb.mkdir(exist_ok=True)
            return sb
    sb = Path.cwd() / "sandbox"
    sb.mkdir(exist_ok=True)
    return sb


def _save_result(result: dict, name: str) -> str:
    """Always persist the run to sandbox/ as timestamped JSON; return the path.

    Records every run (dry-run, execute, verify) so there's a durable trade log —
    e.g. the order.bracket / binding details that TWS alone doesn't reconstruct.
    """
    ts = datetime.now(_NY).strftime("%Y-%m-%d_%H%M%S")
    path = _sandbox_dir() / f"{name}_{ts}.json"
    result["saved_to"] = str(path)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return str(path)


def main():
    parser = argparse.ArgumentParser(
        description="Find best 0DTE credit spreads from Interactive Brokers"
    )
    parser.add_argument(
        "symbol",
        nargs="?",
        help="Underlying symbol (e.g. SPX, NDX, RUT, VIX, AAPL, SPY). Optional for --verify-stops.",
    )
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
        help="Cap the |delta| of the short leg(s) at ENTRY. "
        "Default: 0.10 for indexes, 0.20 for stocks (override here).",
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
        default=None,
        help="Premium-cap stop: close when the spread reaches this multiple of the credit "
        "(0 disables it). Default: per-symbol preset (see STOP_PRESETS), else 2.0.",
    )
    parser.add_argument(
        "--stop-buffer",
        type=float,
        default=None,
        help="Points before the short strike to trigger the level stop "
        "(default: per-symbol preset, else 0 = at the strike)",
    )
    parser.add_argument(
        "--stop-delta",
        type=float,
        default=None,
        help="Also stop when the short-leg delta reaches this level, e.g. 0.30 "
        "(default: per-symbol preset)",
    )
    parser.add_argument(
        "--profit-target",
        type=float,
        default=None,
        help="Buy back after capturing this fraction of the credit, e.g. 0.75 = 75%% "
        "(0 disables). Default: per-symbol preset, else 0.75.",
    )
    parser.add_argument(
        "--time-exit",
        default=None,
        help="Flatten remaining spreads at this ET time, e.g. 15:30 ('none' disables). "
        "Default: per-symbol preset, else 15:30.",
    )
    parser.add_argument(
        "--fill-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for the entry to fill before cancelling it (stops need a fill)",
    )
    parser.add_argument("--expiries", action="store_true", help="List available expiries and exit")
    parser.add_argument(
        "--verify-stops",
        action="store_true",
        help="Check that every open 0DTE spread has a resting protective stop, then exit",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="With --verify-stops: place a strike-level stop on any unprotected position",
    )
    parser.add_argument("--port", type=int, default=7497, help="IB port (7497=paper, 7496=live)")

    args = parser.parse_args()
    ga = generated_at_str()

    if args.verify_stops:
        result = asyncio.run(
            verify_zdte_stops(port=args.port, account=args.account, repair=args.repair)
        )
        name = "verify_stops"
    else:
        if not args.symbol:
            parser.error("symbol is required (except with --verify-stops)")
        symbol = args.symbol.upper()
        if args.expiries:
            result = asyncio.run(get_0dte_expiries(symbol, port=args.port))
            name = f"{symbol}_0dte_expiries"
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
                    profit_target=args.profit_target,
                    time_exit=_normalize_time_exit(args.time_exit),
                    fill_timeout=args.fill_timeout,
                )
            )
            mode = "exec" if args.execute else "dryrun"
            name = f"{symbol}_0dte_{args.spread_type}_{mode}"

    result["generated_at"] = ga
    result.setdefault("data_delay", "real-time")  # broker sets this when it knows
    _save_result(result, name)  # always persist a copy to sandbox/

    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()

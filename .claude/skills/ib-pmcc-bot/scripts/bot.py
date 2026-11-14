# ABOUTME: CLI wrapper for the operational PMCC bot. Dry-run by default; --execute places orders.

import argparse
import asyncio
import json

from trading_skills.broker.pmcc_bot import run_pmcc_bot

DEFAULT_UNIVERSE = "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,AMD"


def main() -> None:
    p = argparse.ArgumentParser(description="Operational PMCC bot (scan, open, manage).")
    p.add_argument(
        "symbols",
        nargs="?",
        default=DEFAULT_UNIVERSE,
        help="Comma-separated tickers to scan for new diagonals.",
    )
    p.add_argument("--port", type=int, default=7497, help="IB port (7497 paper, 7496 live).")
    p.add_argument("--account", default=None, help="Specific account ID (default: first managed).")
    p.add_argument("--top-n", type=int, default=3, help="Max new diagonals to open per cycle.")
    p.add_argument("--min-score", type=float, default=0.0, help="Minimum PMCC score to open.")
    p.add_argument(
        "--decay-threshold",
        type=float,
        default=0.70,
        help="Close+reroll short once this fraction of premium has decayed (0-1).",
    )
    p.add_argument(
        "--execute",
        action="store_true",
        help="Place real orders. Without this flag the bot only previews (dry-run).",
    )
    args = p.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    result = asyncio.run(
        run_pmcc_bot(
            symbols=symbols,
            port=args.port,
            account=args.account,
            top_n=args.top_n,
            min_score=args.min_score,
            decay_threshold=args.decay_threshold,
            dry_run=not args.execute,
        )
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

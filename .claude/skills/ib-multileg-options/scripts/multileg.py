#!/usr/bin/env python3
# ABOUTME: CLI for the multi-leg options strategy engine using the IB option chain.
# ABOUTME: Classifies regime, proposes Iron Duck / butterfly / woodpecker / Time Fly trades.

import argparse
import asyncio
import json
import sys
from pathlib import Path

from trading_skills.broker.multileg import propose_trades
from trading_skills.multileg import BUILDERS
from trading_skills.utils import generated_at_str

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "references/multileg_options_config.yaml"


def main():
    parser = argparse.ArgumentParser(description="Propose multi-leg option trades from IB data")
    parser.add_argument("symbol", help="Underlying (SPX, RUT, NDX, SPY, QQQ, IWM, AAPL...)")
    parser.add_argument("--dte", type=float, default=14, help="Target days to expiry (default 14)")
    parser.add_argument("--expiry", help="Exact expiry YYYYMMDD (overrides --dte)")
    parser.add_argument(
        "--strategy",
        help=f"Comma list or 'all' (default: auto from regime). Options: {', '.join(BUILDERS)}",
    )
    parser.add_argument("--direction", choices=["BULL", "BEAR", "NEUTRAL"], help="Override")
    parser.add_argument("--earnings", action="store_true", help="Earnings before expiry")
    parser.add_argument("--account-value", type=float, help="Account value for sizing")
    parser.add_argument("--include-disabled", action="store_true", help="Allow Jade Lizard")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Strategy config YAML")
    parser.add_argument("--rate", type=float, default=0.04, help="Risk-free rate")
    parser.add_argument("--max-strikes", type=int, default=160, help="Max strikes per side")
    parser.add_argument("--port", type=int, default=7496, help="IB port (7497=paper, 7496=live)")
    args = parser.parse_args()

    strategies = None
    if args.strategy:
        strategies = list(BUILDERS) if args.strategy == "all" else args.strategy.split(",")

    result = asyncio.run(
        propose_trades(
            args.symbol,
            port=args.port,
            target_dte=args.dte,
            expiry=args.expiry,
            strategies=strategies,
            direction=args.direction,
            earnings=args.earnings,
            account_value=args.account_value,
            include_disabled=args.include_disabled,
            config_path=args.config,
            rate=args.rate,
            max_strikes=args.max_strikes,
        )
    )
    if not result.get("success"):
        print(json.dumps(result))
        sys.exit(1)
    result["generated_at"] = generated_at_str()
    if result.get("stale_quotes"):
        result["data_delay"] = "stalled - using yesterday's data"
    else:
        result["data_delay"] = "real-time if subscribed, else 15min delayed"
    print(json.dumps(result, indent=2, default=float))


if __name__ == "__main__":
    main()

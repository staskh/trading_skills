#!/usr/bin/env python3
# ABOUTME: CLI wrapper for the EMA9/EMA21 + VIX/VXN regime 0DTE strategy.
# ABOUTME: Parses args, delegates to trading_skills.broker.ema_vix, saves output.
"""
EMA + VIX/VXN 0DTE strategy entry point.

Signal logic (default — bare EMA cross):
  1. Vol index >= threshold (default 20) → skip, no trade.
     NDX/QQQ are gated on VXN (Nasdaq-100 vol); all other symbols on VIX.
  2. EMA9 last crossed ABOVE EMA21 → bull_put.
  3. EMA9 last crossed BELOW EMA21 → bear_call.
  4. (With --ic-gate) EMA9/EMA21 gap within --ic-threshold% at ref bar → iron_condor.

Two optional confirmation gates (both OFF by default; opt in per run):
  --rr-gate    Require both the 9:30 ET (13:30 UTC) and 10:00 ET (14:00 UTC)
               bars to be red before taking a Bear Call (EMA-down). If not
               confirmed → no trade.
  --time-gate  Require today's 9:30 ET and 10:00 ET bars to exist (i.e. run at
               10:30 ET or later) and anchor the EMA-cross lookback to the
               10:00 ET bar. Without it, the lookback anchors to the latest
               available bar, so the strategy can run at any time of day.

Iron condor gate (opt in with --ic-gate):
  --ic-gate    When the EMA9/EMA21 gap at the reference bar is within
               --ic-threshold%, select iron_condor instead of a directional
               spread. Flat EMAs can precede a breakout — opt in deliberately.
  --ic-threshold  Gap threshold in percent for EMA-flat detection (default: 0.15).

Position sizing uses the existing zero_dte library (budget / max_loss_per_contract).
Strike targeting defaults to --target-delta 0.12, which approximates 1.5% OTM
at VIX 15-19. Override with --target-delta if needed.

The strategy logic lives in trading_skills.broker.ema_vix (also used by the MCP
server); this script only handles CLI args and sandbox output.

Usage:
  uv run python scripts/ema_vix_0dte.py NDX --budget 50000 --port 7496
  uv run python scripts/ema_vix_0dte.py NDX --budget 50000 --port 7496 --rr-gate --time-gate
  uv run python scripts/ema_vix_0dte.py SPX --budget 50000 --port 7496 --execute --account U790497
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from trading_skills.broker.ema_vix import run_ema_vix_strategy
from trading_skills.utils import generated_at_str

NY = ZoneInfo("America/New_York")


def _sandbox_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            sb = parent / "sandbox"
            sb.mkdir(exist_ok=True)
            return sb
    sb = Path.cwd() / "sandbox"
    sb.mkdir(exist_ok=True)
    return sb


def _save_result(result: dict, name: str) -> str:
    ts = datetime.now(NY).strftime("%Y-%m-%d_%H%M%S")
    path = _sandbox_dir() / f"{name}_{ts}.json"
    result["saved_to"] = str(path)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return str(path)


def main():
    parser = argparse.ArgumentParser(
        description="EMA9/EMA21 + VIX/VXN 0DTE strategy — auto-selects bull_put, bear_call, or iron_condor"
    )
    parser.add_argument("symbol", help="Underlying (NDX, SPX, RUT, …)")

    # Strategy-specific
    parser.add_argument(
        "--vix-threshold",
        type=float,
        default=None,
        help="Skip trade if vol index >= this value. Default is per-index: "
        "VXN 35 for NDX/QQQ, VIX 20 otherwise.",
    )
    parser.add_argument(
        "--target-delta",
        type=float,
        default=None,
        help="Short-leg delta target (default: 0.12, ~1.5%% OTM at VIX<20)",
    )
    parser.add_argument(
        "--rr-gate",
        action="store_true",
        help="Require red→red (9:30 + 10:00 ET bars both red) to confirm a Bear "
        "Call on an EMA-down signal (default: off)",
    )
    parser.add_argument(
        "--time-gate",
        action="store_true",
        help="Require today's 9:30 + 10:00 ET bars (run at 10:30 ET or later) and "
        "anchor the EMA-cross lookback to the 10:00 ET bar (default: off)",
    )
    parser.add_argument(
        "--ic-gate",
        action="store_true",
        help="When EMA9/EMA21 gap is within --ic-threshold%% at the reference bar, "
        "auto-select iron_condor instead of a directional spread (default: off)",
    )
    parser.add_argument(
        "--ic-threshold",
        type=float,
        default=0.15,
        help="EMA gap threshold in percent for iron condor auto-selection (default: 0.15)",
    )

    # Pass-through to find_0dte_spreads (same flags as zero_dte.py)
    parser.add_argument("--budget", type=float, default=50_000.0)
    parser.add_argument("--expiry", default=None)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--min-pop", type=float, default=0.0)
    parser.add_argument("--max-width", type=float, default=None)
    parser.add_argument("--delta", type=float, default=None)
    parser.add_argument("--rv-ratio", type=float, default=0.85)
    parser.add_argument("--allow-stale", action="store_true")
    parser.add_argument("--no-events", action="store_true")
    parser.add_argument("--gex", action="store_true")
    parser.add_argument("--gex-weight", choices=("auto", "volume", "oi"), default="auto")
    parser.add_argument("--account", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--pick", type=int, default=1)
    parser.add_argument("--limit", type=float, default=None)
    parser.add_argument("--limit-frac", type=float, default=None)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--stop-mult", type=float, default=None)
    parser.add_argument("--stop-buffer", type=float, default=None)
    parser.add_argument("--stop-delta", type=float, default=None)
    parser.add_argument("--profit-target", type=float, default=None)
    parser.add_argument("--time-exit", default=None)
    parser.add_argument("--fill-timeout", type=float, default=60.0)
    parser.add_argument("--port", type=int, default=7496)
    parser.add_argument(
        "--client-id",
        type=int,
        default=61,
        help="IB client ID for bar fetch (default: 61; must differ from zero_dte's ID)",
    )

    args = parser.parse_args()
    ga = generated_at_str()

    result = asyncio.run(
        run_ema_vix_strategy(
            args.symbol,
            budget=args.budget,
            port=args.port,
            vix_threshold=args.vix_threshold,
            target_delta=args.target_delta,
            rr_gate=args.rr_gate,
            time_gate=args.time_gate,
            ic_gate=args.ic_gate,
            ic_threshold=args.ic_threshold,
            expiry=args.expiry,
            account=args.account,
            execute=args.execute,
            pick=args.pick,
            limit=args.limit,
            limit_frac=args.limit_frac,
            replace=args.replace,
            top=args.top,
            min_pop=args.min_pop,
            max_width=args.max_width,
            delta=args.delta,
            rv_ratio=args.rv_ratio,
            allow_stale=args.allow_stale,
            no_events=args.no_events,
            gex=args.gex,
            gex_weight=args.gex_weight,
            stop_mult=args.stop_mult,
            stop_buffer=args.stop_buffer,
            stop_delta=args.stop_delta,
            profit_target=args.profit_target,
            time_exit=args.time_exit,
            fill_timeout=args.fill_timeout,
            client_id=args.client_id,
        )
    )
    result["generated_at"] = ga
    result.setdefault("data_delay", "real-time")

    mode = "exec" if args.execute else "dryrun"
    stype = result.get("spread_type") or "noop"
    signal = result.get("signal", "").lower().replace("+", "_")
    name = f"{args.symbol.upper()}_0dte_ema_{signal}_{stype}_{mode}"
    _save_result(result, name)

    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()

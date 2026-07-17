#!/usr/bin/env python3
# ABOUTME: EMA9/EMA21 + VIX<20 regime strategy wrapper for the 0DTE skill.
# ABOUTME: Determines bull_put vs bear_call from 30-min bar signals, then
# ABOUTME: delegates spread selection and execution to find_0dte_spreads.
"""
EMA + VIX 0DTE strategy entry point.

Run at 10:30 ET (14:30 UTC) for same-day 0DTE entry.

Signal logic (mirrors the 360-day backtest):
  1. VIX >= threshold (default 20) → skip, no trade.
  2. EMA9 last crossed ABOVE EMA21 → bull_put.
  3. EMA9 last crossed BELOW EMA21 AND both the 9:30 ET bar (13:30 UTC)
     and 10:00 ET bar (14:00 UTC) are red → bear_call.
  4. EMA9 crossed below but R->R not confirmed → no trade.

Position sizing uses the existing zero_dte library (budget / max_loss_per_contract).
Strike targeting defaults to --target-delta 0.12, which approximates 1.5% OTM
at VIX 15-19. Override with --target-delta if needed.

Usage:
  uv run python scripts/ema_vix_0dte.py NDX --budget 50000 --port 7496
  uv run python scripts/ema_vix_0dte.py SPX --budget 50000 --port 7496 --execute --account U790497
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yfinance as yf
from ib_async import IB, Index, Stock

from trading_skills.broker.zero_dte import find_0dte_spreads
from trading_skills.utils import generated_at_str

UTC = ZoneInfo("UTC")
NY = ZoneInfo("America/New_York")

EMA_FAST = 9
EMA_SLOW = 21
BAR1_H, BAR1_M = 13, 30  # 9:30 ET
BAR2_H, BAR2_M = 14, 0  # 10:00 ET

# Index contracts: symbol -> (exchange, currency)
INDEX_MAP = {
    "NDX": ("NASDAQ", "USD"),
    "SPX": ("CBOE", "USD"),
    "RUT": ("RUSSELL", "USD"),
    "VIX": ("CBOE", "USD"),
}


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


def _ema_series(closes: list[float], period: int) -> list[float | None]:
    if len(closes) < period:
        return [None] * len(closes)
    mult = 2.0 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    result.append(sum(closes[:period]) / period)
    for c in closes[period:]:
        result.append(result[-1] * (1 - mult) + c * mult)  # type: ignore[operator]
    return result


def _vix_value() -> float:
    """Return most-recent available VIX close from yfinance (prior-day close at open)."""
    try:
        raw = yf.download("^VIX", period="5d", interval="1d", auto_adjust=True, progress=False)
        if hasattr(raw.columns, "get_level_values"):
            raw.columns = raw.columns.get_level_values(0)
        series = raw["Close"].dropna()
        if series.empty:
            return 18.0
        return float(series.iloc[-1])
    except Exception:
        return 18.0


async def _fetch_bars(symbol: str, port: int, client_id: int = 61) -> list[dict]:
    """Fetch 10 trading days of 30-min RTH bars for symbol."""
    ib = IB()
    try:
        await ib.connectAsync("127.0.0.1", port, clientId=client_id, readonly=True)
        if symbol.upper() in INDEX_MAP:
            exch, ccy = INDEX_MAP[symbol.upper()]
            contract = Index(symbol.upper(), exch, ccy)
        else:
            contract = Stock(symbol.upper(), "SMART", "USD")
        await ib.qualifyContractsAsync(contract)
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr="10 D",
            barSizeSetting="30 mins",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2,
            keepUpToDate=False,
        )
        result = []
        for b in bars:
            dt_utc = b.date.astimezone(UTC) if hasattr(b.date, "astimezone") else b.date
            result.append(
                {
                    "dt": dt_utc,
                    "open": b.open,
                    "close": b.close,
                }
            )
        result.sort(key=lambda x: x["dt"])
        return result
    finally:
        ib.disconnect()


def _detect_signal(bars: list[dict]) -> tuple[str | None, str, str | None]:
    """
    Returns (spread_type, signal_name, reason_skipped).

    spread_type: 'bull_put' | 'bear_call' | None
    signal_name: human-readable label
    reason_skipped: set when spread_type is None
    """
    if not bars:
        return None, "no-bars", "No bars received from IB"

    closes = [b["close"] for b in bars]
    ema9_s = _ema_series(closes, EMA_FAST)
    ema21_s = _ema_series(closes, EMA_SLOW)
    bar_idx = {b["dt"]: i for i, b in enumerate(bars)}

    # Group bars by ET date, find today's key bars
    today_et = datetime.now(NY).date()
    by_date: dict[date, list[dict]] = defaultdict(list)
    for b in bars:
        by_date[b["dt"].astimezone(NY).date()].append(b)

    today_bars = by_date.get(today_et, [])
    bar1 = next(
        (b for b in today_bars if b["dt"].hour == BAR1_H and b["dt"].minute == BAR1_M), None
    )
    bar2 = next(
        (b for b in today_bars if b["dt"].hour == BAR2_H and b["dt"].minute == BAR2_M), None
    )

    if not bar1 or not bar2:
        return (
            None,
            "missing-bars",
            (
                f"Need 9:30 ET and 10:00 ET bars — found bar1={'yes' if bar1 else 'no'}, "
                f"bar2={'yes' if bar2 else 'no'}. Run at 10:30 ET or later."
            ),
        )

    # R->R signal: both 9:30 and 10:00 ET bars must be red
    b1_red = bar1["close"] < bar1["open"]
    b2_red = bar2["close"] < bar2["open"]
    rr_signal = b1_red and b2_red

    # Last EMA crossover looking backward from bar2
    idx2 = bar_idx.get(bar2["dt"])
    last_cross_dir = None
    if idx2 is not None:
        for i in range(idx2, 0, -1):
            ef_c, es_c = ema9_s[i], ema21_s[i]
            ef_p, es_p = ema9_s[i - 1], ema21_s[i - 1]
            if None in (ef_c, es_c, ef_p, es_p):
                continue
            if ef_p >= es_p and ef_c < es_c:
                last_cross_dir = "down"
                break
            elif ef_p <= es_p and ef_c > es_c:
                last_cross_dir = "up"
                break

    if last_cross_dir is None:
        return None, "no-cross", "No EMA9/EMA21 crossover found in recent history"

    if last_cross_dir == "up":
        return "bull_put", "EMA-Up", None

    # EMA is down — need R->R to take Bear Call
    if rr_signal:
        return "bear_call", "EMA-Dn+RR", None

    b1_str = "red" if b1_red else "green"
    b2_str = "red" if b2_red else "green"
    return (
        None,
        "EMA-Dn-no-RR",
        (
            f"EMA crossed down but R->R not confirmed "
            f"(9:30 bar={b1_str}, 10:00 bar={b2_str}) — skip Bear Call"
        ),
    )


async def run(args: argparse.Namespace) -> dict:
    symbol = args.symbol.upper()

    # ── 1. VIX regime filter ──────────────────────────────────────────────
    vix_val = _vix_value()
    if vix_val >= args.vix_threshold:
        result = {
            "success": False,
            "symbol": symbol,
            "strategy": "ema_vix",
            "vix": round(vix_val, 2),
            "vix_threshold": args.vix_threshold,
            "signal": "VIX-SKIP",
            "spread_type": None,
            "reason": f"VIX {vix_val:.1f} >= {args.vix_threshold} — no trade today",
            "generated_at": generated_at_str(),
            "data_delay": "real-time",
        }
        return result

    # ── 2. Fetch bars and detect EMA signal ───────────────────────────────
    bars = await _fetch_bars(symbol, port=args.port, client_id=args.client_id)
    spread_type, signal_name, skip_reason = _detect_signal(bars)

    if spread_type is None:
        result = {
            "success": False,
            "symbol": symbol,
            "strategy": "ema_vix",
            "vix": round(vix_val, 2),
            "signal": signal_name,
            "spread_type": None,
            "reason": skip_reason,
            "generated_at": generated_at_str(),
            "data_delay": "real-time",
        }
        return result

    # ── 3. Delegate to find_0dte_spreads ──────────────────────────────────
    target_delta = args.target_delta if args.target_delta is not None else 0.12
    result = await find_0dte_spreads(
        symbol,
        spread_type=spread_type,
        budget=args.budget,
        expiry=args.expiry,
        port=args.port,
        account=args.account,
        execute=args.execute,
        pick=args.pick,
        limit=args.limit,
        limit_frac=args.limit_frac,
        replace=args.replace,
        top=args.top,
        min_pop=args.min_pop,
        max_width=args.max_width,
        max_short_delta=args.delta,
        target_delta=target_delta,
        rv_ratio=args.rv_ratio,
        allow_stale=args.allow_stale,
        fetch_events=not args.no_events,
        gex=args.gex,
        gex_weight=args.gex_weight,
        stop_mult=args.stop_mult,
        stop_buffer=args.stop_buffer,
        stop_delta=args.stop_delta,
        profit_target=args.profit_target,
        time_exit=args.time_exit,
        fill_timeout=args.fill_timeout,
    )

    # Annotate with strategy metadata
    result["strategy"] = "ema_vix"
    result["signal"] = signal_name
    result["vix"] = round(vix_val, 2)
    result["vix_threshold"] = args.vix_threshold
    return result


def main():
    parser = argparse.ArgumentParser(
        description="EMA9/EMA21 + VIX<20 0DTE strategy — auto-selects bull_put or bear_call"
    )
    parser.add_argument("symbol", help="Underlying (NDX, SPX, RUT, …)")

    # Strategy-specific
    parser.add_argument(
        "--vix-threshold",
        type=float,
        default=20.0,
        help="Skip trade if VIX >= this value (default: 20.0)",
    )
    parser.add_argument(
        "--target-delta",
        type=float,
        default=None,
        help="Short-leg delta target (default: 0.12, ~1.5%% OTM at VIX<20)",
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

    result = asyncio.run(run(args))
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

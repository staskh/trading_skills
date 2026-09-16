#!/usr/bin/env python3
# ABOUTME: EMA9/EMA21 + VIX/VXN regime 0DTE strategy — signal detection + runner.
# ABOUTME: Auto-selects bull_put or bear_call from 30-min bars, then delegates
# ABOUTME: spread selection and execution to find_0dte_spreads.
"""
EMA + VIX/VXN 0DTE strategy.

Signal logic (default — bare EMA cross):
  1. Vol index >= threshold -> skip, no trade. NDX/QQQ are gated on VXN
     (Nasdaq-100 vol, default cutoff 35); all other symbols on VIX (default 20).
  2. EMA9 last crossed ABOVE EMA21 -> bull_put.
  3. EMA9 last crossed BELOW EMA21 -> bear_call.
  4. EMA9 ≈ EMA21 (gap within ic_threshold%) AND ic_gate=True -> iron_condor.

Two optional confirmation gates (both OFF by default):
  rr_gate    Require today's two most recently closed bars to be red
             before taking a Bear Call (EMA-down). If not confirmed -> no trade.
  time_gate  Require today's 9:30 ET and 10:00 ET bars to exist (i.e. run at
             10:30 ET or later) and anchor the EMA-cross lookback to the 10:00
             ET bar. Without it, the lookback anchors to the latest available
             bar, so the strategy can run at any time of day.

Iron condor gate (off by default):
  ic_gate       Enable iron condor when EMAs are flat (neutral regime).
  ic_threshold  Max abs EMA gap (as % of EMA21) to qualify as flat.
                Default 0.15% (~44pts on NDX at 29000). When the gap exceeds
                this the last-cross direction is used as normal.

This module holds the reusable strategy logic so it can be driven from both the
CLI script (ema_vix_0dte.py) and the MCP server.
"""

import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ib_async import IB, Index, Stock

from trading_skills.broker.zero_dte import DEFAULT_BUDGET_FRAC, find_0dte_spreads
from trading_skills.utils import generated_at_str

UTC = ZoneInfo("UTC")
NY = ZoneInfo("America/New_York")

EMA_FAST = 9
EMA_SLOW = 21
BAR1_H, BAR1_M = 13, 30  # 9:30 ET
BAR2_H, BAR2_M = 14, 0  # 10:00 ET
BAR_SPAN = timedelta(minutes=30)  # the bar size these gates reason about

# Index contracts: symbol -> (exchange, currency)
INDEX_MAP = {
    "NDX": ("NASDAQ", "USD"),
    "SPX": ("CBOE", "USD"),
    "RUT": ("RUSSELL", "USD"),
    "VIX": ("CBOE", "USD"),
}

# Symbols whose natural volatility gauge is VXN (Nasdaq-100 vol) rather than VIX.
VXN_SYMBOLS = {"NDX", "NDXP", "QQQ", "MNX"}

# Default vol-gate cutoffs per index. VXN typically prints several points above
# VIX for the same regime, so it gets a higher default cutoff.
DEFAULT_THRESHOLD = {"VIX": 20.0, "VXN": 35.0}


def _vol_index_for(symbol: str) -> str:
    """Return the IB symbol of the vol gauge for `symbol`.

    NDX/QQQ and friends use VXN (CBOE Nasdaq-100 Volatility Index); everything
    else uses VIX. Both trade as CBOE Index contracts.
    """
    return "VXN" if symbol.upper() in VXN_SYMBOLS else "VIX"


def _ema_series(closes: list[float], period: int) -> list[float | None]:
    if len(closes) < period:
        return [None] * len(closes)
    mult = 2.0 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    result.append(sum(closes[:period]) / period)
    for c in closes[period:]:
        result.append(result[-1] * (1 - mult) + c * mult)  # type: ignore[operator]
    return result


def _bar_date(bar) -> date:
    """The calendar date of a historical bar, whether it carries a date or datetime."""
    raw = bar.date
    return raw.date() if isinstance(raw, datetime) else raw


async def _fetch_vol_index(ib, vol_symbol: str) -> tuple[float | None, float | None]:
    """Return (intraday, prior_day_close) for the vol index, both from IB.

    Either is None when IB gives no reading. The vol gate is the strategy's only
    "stand down" check, so a stand-in number here would decide a live trade.
    """
    contract = Index(vol_symbol, "CBOE", "USD")
    try:
        await ib.qualifyContractsAsync(contract)
    except Exception:
        return None, None

    intraday = prior = None
    try:
        minute_bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr="1800 S",
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=2,
            keepUpToDate=False,
        )
        if minute_bars:
            intraday = float(minute_bars[-1].close)
    except Exception:
        pass

    try:
        daily_bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr="5 D",
            barSizeSetting="1 day",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2,
            keepUpToDate=False,
        )
        # IB includes today's in-progress bar during RTH; the gate wants the close
        # of the previous session, so drop anything dated today.
        today_et = datetime.now(NY).date()
        settled = [b for b in daily_bars if _bar_date(b) < today_et]
        if settled:
            prior = float(settled[-1].close)
    except Exception:
        pass

    return intraday, prior


async def _fetch_bars(
    symbol: str,
    vol_symbol: str,
    port: int,
    client_id: int = 61,
) -> tuple[list[dict], float | None, float | None, str]:
    """Fetch 30-min RTH bars + both vol-index readings from IB, one connection.

    Returns (bars, vix_intraday, vix_prior, vix_source). Everything comes from
    IB: one decision must not be assembled from two books.
    """
    ib = IB()
    try:
        await ib.connectAsync("127.0.0.1", port, clientId=client_id, readonly=True)

        # ── Symbol bars (10 trading days, 30-min RTH) ─────────────────────
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
            result.append({"dt": dt_utc, "open": b.open, "close": b.close})
        result.sort(key=lambda x: x["dt"])

        # ── Vol index (VIX/VXN): intraday + prior-day close, both from IB ──
        vix_intraday, vix_prior = await _fetch_vol_index(ib, vol_symbol)
        vix_source = "ib" if (vix_intraday is not None or vix_prior is not None) else "unavailable"

        return result, vix_intraday, vix_prior, vix_source
    finally:
        ib.disconnect()


def _detect_signal(
    bars: list[dict],
    rr_gate: bool = False,
    time_gate: bool = False,
    ic_gate: bool = False,
    ic_threshold: float = 0.15,
) -> tuple[str | None, str, str | None, float | None]:
    """
    Returns (spread_type, signal_name, reason_skipped, ema_gap_pct).

    spread_type:  'bull_put' | 'bear_call' | 'iron_condor' | None
    signal_name:  human-readable label
    reason_skipped: set when spread_type is None
    ema_gap_pct:  (EMA9 - EMA21) / EMA21 * 100 at the ref bar, or None

    Defaults (all gates off): a bare EMA9/EMA21 cross picks the direction —
    up → bull_put, down → bear_call — anchored to the latest available bar, so
    it runs at any time of day.

    rr_gate=True:   an EMA-down only becomes a Bear Call if today's two most
                    recently CLOSED bars are both red (red→red); otherwise no
                    trade. Reads current momentum, whenever the run happens.
    time_gate=True: require today's 9:30 ET and 10:00 ET bars to exist (run at
                    10:30 ET or later) and anchor the EMA-cross lookback to the
                    10:00 ET bar.
    ic_gate=True:   when EMA9 and EMA21 are within ic_threshold% of each other
                    (neutral/flat regime), select iron_condor instead of a
                    directional spread. Without this flag the last-cross direction
                    is used even when EMAs are flat.
    """
    if not bars:
        return None, "no-bars", "No bars received from IB", None

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

    # Red->red confirmation reads today's two most recently CLOSED bars, so it
    # reflects momentum at the moment of the run. bar1/bar2 below stay pinned to
    # 9:30/10:00 because the time gate's job is a fixed morning anchor.
    now_utc = datetime.now(NY).astimezone(UTC)
    closed_today = [b for b in today_bars if b["dt"] + BAR_SPAN <= now_utc]
    rr_bars = closed_today[-2:]

    bar1 = next(
        (b for b in today_bars if b["dt"].hour == BAR1_H and b["dt"].minute == BAR1_M), None
    )
    bar2 = next(
        (b for b in today_bars if b["dt"].hour == BAR2_H and b["dt"].minute == BAR2_M), None
    )

    # Time gate: only enforced when opted in.
    if time_gate and (not bar1 or not bar2):
        return (
            None,
            "missing-bars",
            (
                f"Need 9:30 ET and 10:00 ET bars — found bar1={'yes' if bar1 else 'no'}, "
                f"bar2={'yes' if bar2 else 'no'}. Run at 10:30 ET or later."
            ),
            None,
        )

    # Reference bar for the EMA-cross lookback:
    #   time_gate on  → the 10:00 ET bar (fixed morning anchor)
    #   time_gate off → the latest bar available today, else the latest overall
    if time_gate and bar2:
        ref_bar = bar2
    elif today_bars:
        ref_bar = today_bars[-1]
    else:
        ref_bar = bars[-1]

    ref_idx = bar_idx.get(ref_bar["dt"])

    # Compute EMA gap at the reference bar (positive = EMA9 above EMA21).
    ema_gap_pct: float | None = None
    if ref_idx is not None:
        ef_ref, es_ref = ema9_s[ref_idx], ema21_s[ref_idx]
        if ef_ref is not None and es_ref is not None and es_ref != 0:
            ema_gap_pct = round((ef_ref - es_ref) / es_ref * 100, 4)

    # Iron condor gate: when EMAs are within ic_threshold% and ic_gate is on,
    # treat the market as neutral and propose an iron condor instead of picking
    # a directional spread. Flat EMAs can precede a breakout — the user must
    # opt in explicitly with --ic-gate.
    if ic_gate and ema_gap_pct is not None and abs(ema_gap_pct) <= ic_threshold:
        return "iron_condor", "EMA-Flat", None, ema_gap_pct

    last_cross_dir = None
    if ref_idx is not None:
        for i in range(ref_idx, 0, -1):
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
        return None, "no-cross", "No EMA9/EMA21 crossover found in recent history", ema_gap_pct

    if last_cross_dir == "up":
        return "bull_put", "EMA-Up", None, ema_gap_pct

    # EMA is down → Bear Call. The red→red confirmation only applies with rr_gate.
    if not rr_gate:
        return "bear_call", "EMA-Dn", None, ema_gap_pct

    # rr_gate on: need two closed bars today, and both red.
    if len(rr_bars) < 2:
        return (
            None,
            "missing-bars-rr",
            (
                f"rr_gate needs two closed bars today — found {len(rr_bars)}. "
                "Wait for the session to print another bar."
            ),
            ema_gap_pct,
        )

    b1, b2 = rr_bars
    b1_red = b1["close"] < b1["open"]
    b2_red = b2["close"] < b2["open"]
    if b1_red and b2_red:
        return "bear_call", "EMA-Dn+RR", None, ema_gap_pct

    b1_str = "red" if b1_red else "green"
    b2_str = "red" if b2_red else "green"
    b1_et = b1["dt"].astimezone(NY).strftime("%H:%M")
    b2_et = b2["dt"].astimezone(NY).strftime("%H:%M")
    return (
        None,
        "EMA-Dn-no-RR",
        (
            f"EMA crossed down but R->R not confirmed "
            f"({b1_et} bar={b1_str}, {b2_et} bar={b2_str}) — skip Bear Call"
        ),
        ema_gap_pct,
    )


async def run_ema_vix_strategy(
    symbol: str,
    *,
    budget: float | None = None,
    budget_frac: float = DEFAULT_BUDGET_FRAC,
    port: int = 7496,
    vix_threshold: float | None = None,
    target_delta: float | None = None,
    rr_gate: bool = False,
    time_gate: bool = False,
    expiry: str | None = None,
    account: str | None = None,
    execute: bool = False,
    pick: int = 1,
    limit: float | None = None,
    limit_frac: float | None = None,
    replace: bool = False,
    top: int = 5,
    min_pop: float = 0.0,
    max_width: float | None = None,
    delta: float | None = None,
    rv_ratio: float = 0.85,
    allow_stale: bool = False,
    no_events: bool = False,
    gex: bool = False,
    gex_weight: str = "auto",
    stop_mult: float | None = None,
    stop_buffer: float | None = None,
    stop_delta: float | None = None,
    profit_target: float | None = None,
    time_exit: str | None = None,
    fill_timeout: float = 60.0,
    client_id: int = 61,
    ic_gate: bool = False,
    ic_threshold: float = 0.15,
) -> dict:
    """Run the EMA9/EMA21 + VIX/VXN regime strategy and return the result dict.

    Reads 30-min bars + the live vol index from IB, applies the vol gate, detects
    the EMA signal (auto-selecting bull_put / bear_call), then delegates to
    find_0dte_spreads for strike selection, ranking, and (if execute) placement.
    Returns a dict with success=False and a reason when any gate blocks the trade.
    """
    symbol = symbol.upper()
    vol_symbol = _vol_index_for(symbol)
    # Per-index default cutoff (VXN 35 / VIX 20) unless explicitly overridden.
    if vix_threshold is None:
        vix_threshold = DEFAULT_THRESHOLD[vol_symbol]

    # ── 1. Fetch bars + live intraday vol index from IB (single connection) ─
    try:
        bars, vix_intraday, vix_prior, vix_source = await _fetch_bars(
            symbol, vol_symbol, port=port, client_id=client_id
        )
    except (ConnectionRefusedError, OSError, TimeoutError, asyncio.TimeoutError) as exc:
        return {
            "success": False,
            "symbol": symbol,
            "strategy": "ema_vix",
            "vol_index": vol_symbol,
            "signal": "IB-ERROR",
            "spread_type": None,
            "error": f"Could not connect to IB on port {port}: {exc}",
            "reason": "IB connection failed — is TWS/Gateway running with the API enabled?",
            "generated_at": generated_at_str(),
            "data_delay": "real-time",
        }

    # ── 2. Dual vol gate ──────────────────────────────────────────────────
    # Both intraday vol (current market state) AND prior-day close (regime
    # continuity) must be below the threshold. A market recovering from a
    # high-vol close is still fragile — the prior-day gate blocks those days.
    # NDX/QQQ gate on VXN; everything else on VIX.
    if vix_intraday is None or vix_prior is None:
        missing = [
            name
            for name, value in (("intraday", vix_intraday), ("prior-day", vix_prior))
            if value is None
        ]
        return {
            "success": False,
            "symbol": symbol,
            "strategy": "ema_vix",
            "vol_index": vol_symbol,
            "vix_intraday": round(vix_intraday, 2) if vix_intraday is not None else None,
            "vix_prior": round(vix_prior, 2) if vix_prior is not None else None,
            "vix": None,
            "vix_source": vix_source,
            "vix_threshold": vix_threshold,
            "signal": "VOL-UNAVAILABLE",
            "spread_type": None,
            "reason": (
                f"No {' and '.join(missing)} {vol_symbol} reading — "
                "cannot clear the vol gate, so no trade"
            ),
            "generated_at": generated_at_str(),
            "data_delay": "real-time",
        }

    vix_val = max(vix_intraday, vix_prior)
    skip_vix = vix_intraday >= vix_threshold or vix_prior >= vix_threshold
    if skip_vix:
        blocker = (
            f"intraday {vol_symbol} {vix_intraday:.1f}"
            if vix_intraday >= vix_threshold
            else f"prior-day {vol_symbol} {vix_prior:.1f}"
        )
        return {
            "success": False,
            "symbol": symbol,
            "strategy": "ema_vix",
            "vol_index": vol_symbol,
            "vix_intraday": round(vix_intraday, 2),
            "vix_prior": round(vix_prior, 2),
            "vix": round(vix_val, 2),
            "vix_source": vix_source,
            "vix_threshold": vix_threshold,
            "signal": "VIX-SKIP",
            "spread_type": None,
            "reason": f"{blocker} >= {vix_threshold} — no trade today",
            "generated_at": generated_at_str(),
            "data_delay": "real-time",
        }

    # ── 3. Detect EMA signal ──────────────────────────────────────────────
    spread_type, signal_name, skip_reason, ema_gap_pct = _detect_signal(
        bars, rr_gate=rr_gate, time_gate=time_gate, ic_gate=ic_gate, ic_threshold=ic_threshold
    )

    if spread_type is None:
        return {
            "success": False,
            "symbol": symbol,
            "strategy": "ema_vix",
            "vol_index": vol_symbol,
            "vix_intraday": round(vix_intraday, 2),
            "vix_prior": round(vix_prior, 2),
            "vix": round(vix_val, 2),
            "vix_source": vix_source,
            "signal": signal_name,
            "spread_type": None,
            "reason": skip_reason,
            "ema_gap_pct": ema_gap_pct,
            "generated_at": generated_at_str(),
            "data_delay": "real-time",
        }

    # ── 4. Delegate to find_0dte_spreads ──────────────────────────────────
    eff_target_delta = target_delta if target_delta is not None else 0.12
    result = await find_0dte_spreads(
        symbol,
        spread_type=spread_type,
        budget=budget,
        budget_frac=budget_frac,
        expiry=expiry,
        port=port,
        account=account,
        execute=execute,
        pick=pick,
        limit=limit,
        limit_frac=limit_frac,
        replace=replace,
        top=top,
        min_pop=min_pop,
        max_width=max_width,
        max_short_delta=delta,
        target_delta=eff_target_delta,
        rv_ratio=rv_ratio,
        allow_stale=allow_stale,
        fetch_events=not no_events,
        gex=gex,
        gex_weight=gex_weight,
        stop_mult=stop_mult,
        stop_buffer=stop_buffer,
        stop_delta=stop_delta,
        profit_target=profit_target,
        time_exit=time_exit,
        fill_timeout=fill_timeout,
    )

    # Annotate with strategy metadata
    result["strategy"] = "ema_vix"
    result["signal"] = signal_name
    result["ema_gap_pct"] = ema_gap_pct
    result["vol_index"] = vol_symbol
    result["vix_intraday"] = round(vix_intraday, 2)
    result["vix_prior"] = round(vix_prior, 2)
    result["vix"] = round(vix_val, 2)
    result["vix_source"] = vix_source
    result["vix_threshold"] = vix_threshold
    return result

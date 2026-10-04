# ABOUTME: IB data layer for the multi-leg options engine (chain with deltas, regime history).
# ABOUTME: Proposes Iron Duck / butterfly / woodpecker / Time Fly trades; never places orders.

import asyncio
import logging
import math
from pathlib import Path

import yaml
from ib_async import IB, Index, Option, Stock

from trading_skills.black_scholes import black_scholes_delta, implied_volatility
from trading_skills.broker.connection import CLIENT_IDS, ib_connection
from trading_skills.multileg import (
    BUILDERS,
    Chain,
    Opt,
    build_strategy,
    classify_regime,
    combo_spread_ok,
    exit_plan,
    gate,
    leg_key,
    legs_to_dict,
    select_strategies,
    size_position,
)
from trading_skills.utils import days_to_expiry, fetch_with_timeout

INDEX_EXCHANGES = {"SPX": "CBOE", "XSP": "CBOE", "RUT": "RUSSELL", "NDX": "NASDAQ"}
DEFAULT_CONFIG = (
    Path(__file__).resolve().parents[3]
    / ".claude/skills/ib-multileg-options/references/multileg_options_config.yaml"
)
BATCH = 50  # stay well under IB's market data line limit


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_CONFIG
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def underlying_contract(symbol: str):
    if symbol in INDEX_EXCHANGES:
        return Index(symbol, INDEX_EXCHANGES[symbol], "USD")
    return Stock(symbol, "SMART", "USD")


async def _spot(ib: IB, contract) -> float | None:
    tickers = await fetch_with_timeout(ib.reqTickersAsync(contract), timeout=15, default=[])
    if not tickers:
        return None
    t = tickers[0]
    price = t.marketPrice()
    if price is None or math.isnan(price) or price <= 0:
        price = t.close if t.close and not math.isnan(t.close) else None
    return price


async def _history(ib: IB, contract, what: str):
    return await fetch_with_timeout(
        ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",
            durationStr="1 Y",
            barSizeSetting="1 day",
            whatToShow=what,
            useRTH=True,
        ),
        timeout=30,
        default=[],
    )


async def _expiry_map(ib: IB, contract) -> dict:
    """expiry -> {trading_class, strikes}, merging all SMART chains (e.g. SPX + SPXW)."""
    chains = await ib.reqSecDefOptParamsAsync(contract.symbol, "", contract.secType, contract.conId)
    pool = [c for c in chains if c.exchange == "SMART"] or list(chains)
    out = {}
    # Prefer the chain with more expirations (weeklies) when an expiry appears in several
    for c in sorted(pool, key=lambda c: len(c.expirations)):
        for exp in c.expirations:
            out[exp] = {"trading_class": c.tradingClass, "strikes": sorted(c.strikes)}
    return out


def pick_expiry(expiries: list[str], target_dte: float, min_dte: float = 1) -> str | None:
    usable = [(e, days_to_expiry(e)) for e in expiries]
    usable = [(e, d) for e, d in usable if d >= min_dte]
    if not usable:
        return None
    return min(usable, key=lambda x: abs(x[1] - target_dte))[0]


def _strike_window(strikes, spot, iv, t, max_per_right):
    sd = max(iv * math.sqrt(t), 0.01)
    lo = spot * math.exp(-max(3.5 * sd, 0.03))
    hi = spot * math.exp(max(3.0 * sd, 0.03))
    sel = [k for k in strikes if lo <= k <= hi]
    if len(sel) > max_per_right:
        sel = sorted(sorted(sel, key=lambda k: abs(k - spot))[:max_per_right])
    return sel


async def _quotes(ib, symbol, expiry, tclass, strikes, spot, t, r) -> list[Opt]:
    contracts = [
        Option(symbol, expiry, k, right, "SMART", tradingClass=tclass, currency="USD")
        for k in strikes
        for right in ("C", "P")
    ]
    ib_logger = logging.getLogger("ib_async")
    prev = ib_logger.level
    ib_logger.setLevel(logging.CRITICAL)
    try:
        qualified = await fetch_with_timeout(
            ib.qualifyContractsAsync(*contracts), timeout=60, default=[]
        )
    finally:
        ib_logger.setLevel(prev)
    qualified = [c for c in qualified if c is not None and c.conId]

    opts = []
    for i in range(0, len(qualified), BATCH):
        batch = qualified[i : i + BATCH]
        tickers = await fetch_with_timeout(ib.reqTickersAsync(*batch), timeout=30, default=[])
        for tk in tickers:
            c = tk.contract
            bid = tk.bid if tk.bid and tk.bid > 0 else None
            ask = tk.ask if tk.ask and tk.ask > 0 else None
            g = tk.modelGreeks
            delta = g.delta if g and g.delta is not None and not math.isnan(g.delta) else None
            iv = g.impliedVol if g and g.impliedVol and not math.isnan(g.impliedVol) else None
            kind = "call" if c.right == "C" else "put"
            if (delta is None or iv is None) and bid is not None and ask is not None:
                iv = iv or implied_volatility((bid + ask) / 2, spot, c.strike, t, r, kind)
                if iv:
                    delta = black_scholes_delta(spot, c.strike, t, r, iv, kind)
            opts.append(Opt(c.strike, c.right, bid, ask, delta, iv))
    return opts


def _dte_window(scfg: dict) -> tuple[float, float]:
    dte = scfg.get("dte") or scfg.get("fly", {}).get("dte") or [1, 45]
    if isinstance(dte, dict):  # iron_duck: index/futures/earnings; stocks use the index window
        dte = dte.get("index", [1, 21])
    return float(dte[0]), float(dte[1])


async def propose_trades(
    symbol: str,
    port: int = 7496,
    target_dte: float = 14,
    expiry: str | None = None,
    strategies: list[str] | None = None,
    direction: str | None = None,
    earnings: bool = False,
    account_value: float | None = None,
    include_disabled: bool = False,
    config_path: str | None = None,
    rate: float = 0.04,
    max_strikes: int = 160,
) -> dict:
    """Classify the regime, build candidate strategies from the IB chain, validate them."""
    cfg = load_config(config_path)
    symbol = symbol.upper()
    try:
        async with ib_connection(port, CLIENT_IDS["multileg"]) as ib:
            ib.reqMarketDataType(4)  # live if subscribed, else delayed/frozen
            und = underlying_contract(symbol)
            q = await fetch_with_timeout(ib.qualifyContractsAsync(und), timeout=15, default=[])
            if not q or q[0] is None or not und.conId:
                return {"success": False, "error": f"Unknown symbol: {symbol}"}

            spot = await _spot(ib, und)
            if not spot:
                return {"success": False, "error": f"No price for {symbol}"}

            bars, iv_bars = await asyncio.gather(
                _history(ib, und, "TRADES"), _history(ib, und, "OPTION_IMPLIED_VOLATILITY")
            )
            iv_series = [b.close for b in iv_bars]

            emap = await _expiry_map(ib, und)
            if not emap:
                return {"success": False, "error": f"No options found for {symbol}"}
            exp = expiry or pick_expiry(list(emap), target_dte)
            if exp not in emap:
                return {"success": False, "error": f"Expiry {exp} not available for {symbol}"}

            emap_tc = emap[exp]["trading_class"]
            dte = days_to_expiry(exp)
            t = max(dte, 1 / 24) / 365
            est_iv = iv_series[-1] if iv_series else 0.25
            strikes = _strike_window(emap[exp]["strikes"], spot, est_iv, t, max_strikes)
            opts = await _quotes(
                ib, symbol, exp, emap[exp]["trading_class"], strikes, spot, t, rate
            )
    except ConnectionError as e:
        return {"success": False, "error": str(e)}

    chain = Chain(opts, spot, t, rate)
    return assemble_proposal(
        symbol,
        chain,
        bars=bars,
        iv_series=iv_series,
        cfg=cfg,
        expiry=exp,
        trading_class=emap_tc,
        dte=dte,
        strategies=strategies,
        direction=direction,
        earnings=earnings,
        account_value=account_value,
        include_disabled=include_disabled,
    )


def assemble_proposal(
    symbol: str,
    chain: Chain,
    bars: list,
    iv_series: list[float],
    cfg: dict,
    expiry: str,
    trading_class: str,
    dte: float,
    strategies: list[str] | None = None,
    direction: str | None = None,
    earnings: bool = False,
    account_value: float | None = None,
    include_disabled: bool = False,
    source: str = "ibkr",
) -> dict:
    """Regime + candidate strategies from already-fetched data (no IB calls).

    `bars` need .close/.high/.low attributes (IB BarData or any equivalent).
    """
    is_index = symbol in INDEX_EXCHANGES
    spot = chain.spot
    exp = expiry
    if not chain._usable("C") or not chain._usable("P"):
        return {"success": False, "error": "chain has no quotes with deltas (market data?)"}

    regime = classify_regime(
        [b.close for b in bars],
        [b.high for b in bars],
        [b.low for b in bars],
        iv_series or [chain.atm_iv()],
        cfg,
        chain,
        earnings,
    )
    if direction:
        regime["direction"] = direction.upper()
        regime["direction_override"] = True

    names = strategies or select_strategies(regime)
    warnings = []
    liq = cfg["universe"]["liquidity"]
    if not is_index:
        floor = liq["min_stock_price_earnings"] if earnings else liq["min_stock_price"]
        if spot < floor:
            warnings.append(f"{symbol} price {spot:.2f} below course minimum {floor}")
    if not iv_series:
        warnings.append("no IB IV history: IV rank/trend unavailable, defaulted to MID/FLAT")

    candidates = []
    for name in names:
        if name not in BUILDERS:
            candidates.append({"strategy": name, "status": "unknown_strategy"})
            continue
        scfg = cfg["strategies"][name]
        if scfg.get("enabled") is False and not include_disabled:
            candidates.append({"strategy": name, "status": "disabled_in_config"})
            continue
        lo, hi = _dte_window(scfg)
        if not lo <= dte <= hi + 0.99:
            candidates.append(
                {"strategy": name, "status": f"skipped: {dte:.1f} DTE outside {lo:g}-{hi:g}"}
            )
            continue
        gated = gate(name, regime)
        built = build_strategy(name, chain, cfg, is_equity=not is_index)
        if "legs" not in built:
            candidates.append({"strategy": name, "status": "build_failed", **built})
            continue
        entry = {
            "strategy": name,
            "status": "gated" if gated else ("valid" if built["passed"] else "failed_validation"),
            "gate_reason": gated,
            "legs": legs_to_dict(built["legs"], exp),
            "analysis": built["analysis"],
            "checks": built["checks"],
            "strike_shifts": built["strike_shifts"],
            "liquidity": combo_spread_ok(built["legs"], cfg),
            "exit_plan": exit_plan(name, cfg, built, exp),
        }
        if account_value:
            entry["sizing"] = size_position(name, cfg, built, account_value, 100)
        candidates.append(entry)

    recommended = next((c["strategy"] for c in candidates if c.get("status") == "valid"), None)
    return {
        "success": True,
        "symbol": symbol,
        "source": source,
        "underlying_price": round(spot, 2),
        "expiry": exp,
        "trading_class": trading_class,
        "dte": round(dte, 2),
        "regime": regime,
        "recommended": recommended,
        "candidates": candidates,
        "warnings": warnings,
        "note": "Proposals only. No orders are placed. Prices are mids; deltas from IB model "
        "greeks (Black-Scholes fallback).",
    }


async def mark_positions(positions: list[dict], port: int = 7496) -> dict:
    """Current spot and leg mids for tracked positions.

    Each position: {symbol, expiry, trading_class, legs: [{strike, right}, ...]}.
    Returns {"spots": {symbol: price}, "mids": {leg_key: mid}}.
    """
    try:
        async with ib_connection(port, CLIENT_IDS["multileg"]) as ib:
            ib.reqMarketDataType(4)
            spots = {}
            for sym in sorted({p["symbol"] for p in positions}):
                und = underlying_contract(sym)
                await fetch_with_timeout(ib.qualifyContractsAsync(und), timeout=15, default=[])
                spots[sym] = await _spot(ib, und)

            contracts, seen = [], set()
            for p in positions:
                for leg in p["legs"]:
                    key = leg_key(p["symbol"], p["expiry"], leg["strike"], leg["right"])
                    if key in seen:
                        continue
                    seen.add(key)
                    contracts.append(
                        Option(
                            p["symbol"],
                            p["expiry"],
                            float(leg["strike"]),
                            leg["right"],
                            "SMART",
                            tradingClass=p.get("trading_class") or "",
                            currency="USD",
                        )
                    )
            qualified = await fetch_with_timeout(
                ib.qualifyContractsAsync(*contracts), timeout=60, default=[]
            )
            qualified = [c for c in qualified if c is not None and c.conId]
            mids = {}
            for i in range(0, len(qualified), BATCH):
                batch = qualified[i : i + BATCH]
                tickers = await fetch_with_timeout(
                    ib.reqTickersAsync(*batch), timeout=30, default=[]
                )
                for tk in tickers:
                    c = tk.contract
                    bid = tk.bid if tk.bid and tk.bid > 0 else None
                    ask = tk.ask if tk.ask and tk.ask > 0 else None
                    if bid is not None and ask is not None:
                        mid = (bid + ask) / 2
                    else:
                        last = tk.last if tk.last and tk.last > 0 else None
                        mid = last if last is not None else tk.close
                    if mid is not None and not math.isnan(mid):
                        key = leg_key(c.symbol, c.lastTradeDateOrContractMonth, c.strike, c.right)
                        mids[key] = mid
            return {"success": True, "spots": spots, "mids": mids}
    except ConnectionError as e:
        return {"success": False, "error": str(e)}

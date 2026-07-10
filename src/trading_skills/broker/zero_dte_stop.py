# ABOUTME: Stop-loss placement for 0DTE credit spreads — level-anchored conditional close orders.
# ABOUTME: Triggers on the underlying (short strike / premium cap / delta) and buys back the combo.

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from ib_async import ComboLeg, Contract, Option, Order, PriceCondition, TimeCondition

from trading_skills.black_scholes import black_scholes_delta, black_scholes_price
from trading_skills.broker.connection import CLIENT_IDS, fetch_positions, ib_connection
from trading_skills.utils import fetch_with_timeout

_NY = ZoneInfo("America/New_York")

_ACTIVE_STOP_STATUSES = {"PendingSubmit", "ApiPending", "PreSubmitted", "Submitted"}

# Close at 2x the credit received (loss = 1x credit) unless overridden.
DEFAULT_STOP_MULT = 2.0

# Per-symbol stop presets — starting points, tune with live data. Keys are symbols;
# "_default" applies to anything unlisted. Any CLI flag the user passes overrides these.
# mult = premium-cap multiple, buffer = points before the short strike, delta = short-delta stop.
STOP_PRESETS = {
    # Wide, high-beta index → lean looser on the premium cap and add a delta backstop
    # so a cheap far-OTM spread doesn't stop out on noise.
    # target = fraction of credit to capture; time_exit = ET flatten time.
    "NDX": {"mult": 3.0, "buffer": 0.0, "delta": 0.35, "target": 0.50, "time_exit": "15:30"},
    "SPX": {"mult": 2.5, "buffer": 0.0, "delta": 0.35, "target": 0.50, "time_exit": "15:30"},
    "RUT": {"mult": 2.0, "buffer": 0.0, "delta": 0.35, "target": 0.50, "time_exit": "15:30"},
    "XSP": {"mult": 2.0, "buffer": 0.0, "delta": 0.35, "target": 0.50, "time_exit": "15:30"},
    "_default": {
        "mult": DEFAULT_STOP_MULT,
        "buffer": 0.0,
        "delta": None,
        "target": 0.50,
        "time_exit": "15:30",
    },
}


def resolve_stop_cfg(symbol, mult, buffer, delta, fill_timeout, target=None, time_exit=None):
    """Merge explicit args over the per-symbol preset over the global default.

    Any of mult/buffer/delta/target/time_exit that is None falls back to the preset
    for `symbol` (then to `_default`). fill_timeout is passed through unchanged.
    A `target` of 0 disables the profit-take; a `time_exit` of "" disables the timer.
    """
    preset = STOP_PRESETS.get(symbol.upper(), STOP_PRESETS["_default"])
    return {
        "mult": preset["mult"] if mult is None else mult,
        "buffer": preset["buffer"] if buffer is None else buffer,
        "delta": preset["delta"] if delta is None else delta,
        "target": preset["target"] if target is None else target,
        "time_exit": preset["time_exit"] if time_exit is None else time_exit,
        "fill_timeout": fill_timeout,
        "preset_symbol": symbol.upper() if symbol.upper() in STOP_PRESETS else "_default",
    }


def _vertical_value(right: str, spot: float, short_k: float, long_k: float, T, r, sigma) -> float:
    """Mark value (cost to close) of a credit vertical at `spot`, per share."""
    ot = "call" if right == "C" else "put"
    return black_scholes_price(spot, short_k, T, r, sigma, ot) - black_scholes_price(
        spot, long_k, T, r, sigma, ot
    )


def _solve_premium_level(right, short_k, long_k, credit, mult, T, r, sigma, spot):
    """Underlying level where the vertical's value = mult*credit. None if unreachable.

    Value is monotonic in spot (rising for a bear call as spot climbs; rising for a
    bull put as spot falls), so a simple bisection converges.
    """
    width = abs(long_k - short_k)
    target = mult * credit
    if target <= 0 or target >= width:
        return None  # cap exceeds defined risk → the strike level governs instead
    lo, hi = (spot, long_k) if right == "C" else (long_k, spot)
    for _ in range(64):
        mid = (lo + hi) / 2
        v = _vertical_value(right, mid, short_k, long_k, T, r, sigma)
        # For a bear call, value rises with spot; for a bull put, value rises as spot falls.
        if right == "C":
            lo, hi = (mid, hi) if v < target else (lo, mid)
        else:
            lo, hi = (lo, mid) if v < target else (mid, hi)
    return round((lo + hi) / 2, 2)


def _solve_delta_level(right, short_k, target_delta, T, r, sigma, spot):
    """Underlying level where the short leg's |delta| = target_delta."""
    ot = "call" if right == "C" else "put"
    lo, hi = (spot, short_k * 1.5) if right == "C" else (short_k * 0.5, spot)
    for _ in range(64):
        mid = (lo + hi) / 2
        d = abs(black_scholes_delta(mid, short_k, T, r, sigma, ot))
        if right == "C":
            lo, hi = (mid, hi) if d < target_delta else (lo, mid)
        else:
            lo, hi = (lo, mid) if d < target_delta else (mid, hi)
    return round((lo + hi) / 2, 2)


def vertical_stop_level(
    right, short_k, long_k, credit, spot, T, r, sigma, *, mult, buffer_pts, target_delta
):
    """Compute the effective stop trigger for one credit vertical.

    Combines up to three candidate underlying levels — the short strike (± buffer),
    the premium-cap level (loss = mult×credit), and an optional short-delta level —
    and takes the one that triggers FIRST on the danger side. Returns a dict with the
    individual levels, the binding trigger, and the condition direction (is_more).
    """
    levels = {}
    strike_level = short_k - buffer_pts if right == "C" else short_k + buffer_pts
    levels["strike"] = round(strike_level, 2)
    if mult:
        levels["premium"] = _solve_premium_level(
            right, short_k, long_k, credit, mult, T, r, sigma, spot
        )
    if target_delta:
        levels["delta"] = _solve_delta_level(right, short_k, target_delta, T, r, sigma, spot)

    usable = {k: v for k, v in levels.items() if v is not None}
    # Danger is up for a bear call (trigger = lowest level above spot), down for a bull
    # put (trigger = highest level below spot).
    if right == "C":
        binding = min(usable, key=usable.get)
        is_more = True
    else:
        binding = max(usable, key=usable.get)
        is_more = False
    return {
        "levels": levels,
        "trigger": usable[binding],
        "is_more": is_more,
        "binding": binding,
    }


def _short_iv(leg: dict) -> float:
    """Short-leg IV as a decimal (leg stores it in %); a sane floor if missing."""
    iv = leg.get("iv")
    return iv / 100.0 if iv else 0.20


def stop_plan(candidate: dict, spot: float, T: float, r: float, *, mult, buffer_pts, target_delta):
    """Build the stop trigger plan(s) for a candidate. Verticals → 1 side; condor → 2."""
    legs = candidate["legs"]
    if candidate["strategy"] == "iron_condor":
        # legs = [put short, put long, call short, call long]
        put_short, put_long, call_short, call_long = legs
        # Split the combined credit across the two sides by their own widths.
        call_side = vertical_stop_level(
            "C",
            call_short["strike"],
            call_long["strike"],
            candidate["net_credit"] / 2,
            spot,
            T,
            r,
            _short_iv(call_short),
            mult=mult,
            buffer_pts=buffer_pts,
            target_delta=target_delta,
        )
        put_side = vertical_stop_level(
            "P",
            put_short["strike"],
            put_long["strike"],
            candidate["net_credit"] / 2,
            spot,
            T,
            r,
            _short_iv(put_short),
            mult=mult,
            buffer_pts=buffer_pts,
            target_delta=target_delta,
        )
        return [{"side": "call", **call_side}, {"side": "put", **put_side}]

    right = "C" if candidate["strategy"] == "bear_call" else "P"
    short_leg, long_leg = legs[0], legs[1]
    plan = vertical_stop_level(
        right,
        short_leg["strike"],
        long_leg["strike"],
        candidate["net_credit"],
        spot,
        T,
        r,
        _short_iv(short_leg),
        mult=mult,
        buffer_pts=buffer_pts,
        target_delta=target_delta,
    )
    return [{"side": right, **plan}]


# --------------------------------------------------------------------------- #
# IB order placement
# --------------------------------------------------------------------------- #
async def _closing_combo(ib, legs_spec, symbol, expiry, exchange, trading_class):
    """Qualify the spread legs and build a BAG that CLOSES it (reversed leg actions)."""
    contracts = [
        Option(
            symbol,
            expiry,
            leg["strike"],
            leg["right"],
            exchange,
            tradingClass=trading_class,
            currency="USD",
        )
        for leg in legs_spec
    ]
    qualified = await fetch_with_timeout(
        ib.qualifyContractsAsync(*contracts), timeout=15, default=[]
    )
    qualified = [q for q in qualified if q is not None and q.conId]
    if len(qualified) != len(legs_spec):
        return None

    combo_legs = []
    for leg, qc in zip(legs_spec, qualified):
        cl = ComboLeg()
        cl.conId = qc.conId
        cl.ratio = 1
        # Reverse the opening action to flatten: sold leg → buy back, bought leg → sell.
        cl.action = "BUY" if leg["action"].upper() == "SELL" else "SELL"
        cl.exchange = exchange
        combo_legs.append(cl)

    combo = Contract()
    combo.symbol = symbol
    combo.secType = "BAG"
    combo.currency = "USD"
    combo.exchange = exchange
    combo.comboLegs = combo_legs
    return combo


def _closing_combo_from_conids(symbol, exchange, leg_conids):
    """Build a closing BAG from already-known leg conIds and their close actions.

    leg_conids: list of (conId, close_action) where close_action is 'BUY'/'SELL'.
    Used by the verify/repair path, which reads legs straight from IB positions.
    """
    combo_legs = []
    for con_id, action in leg_conids:
        cl = ComboLeg()
        cl.conId = con_id
        cl.ratio = 1
        cl.action = action
        cl.exchange = exchange
        combo_legs.append(cl)
    combo = Contract()
    combo.symbol = symbol
    combo.secType = "BAG"
    combo.currency = "USD"
    combo.exchange = exchange
    combo.comboLegs = combo_legs
    return combo


async def _place_conditional_closes(
    ib, combo, width, qty, plans, underlying_conid, underlying_exch, account, order_ref
):
    """Place one conditional buy-to-close order per plan (OCA-linked when >1)."""
    oca = order_ref if len(plans) > 1 else ""
    placed = []
    for plan in plans:
        cond = PriceCondition()
        cond.conId = underlying_conid
        cond.exch = underlying_exch
        cond.isMore = plan["is_more"]
        cond.price = plan["trigger"]

        order = Order()
        order.action = "BUY"  # buy-to-close the reversed combo
        order.orderType = "LMT"
        order.totalQuantity = qty
        order.lmtPrice = round(width, 2)
        order.tif = "DAY"
        order.orderRef = order_ref
        order.account = account
        order.conditions = [cond]
        order.conditionsIgnoreRth = True
        if oca:
            order.ocaGroup = oca
            order.ocaType = 1  # cancel remaining orders on fill

        trade = ib.placeOrder(combo, order)
        placed.append(
            {
                "side": plan["side"],
                "order_id": trade.order.orderId,
                "trigger": plan["trigger"],
                "is_more": plan["is_more"],
                "binding": plan["binding"],
                "levels": plan["levels"],
            }
        )

    await asyncio.sleep(2)
    return {"ok": True, "order_ref": order_ref, "limit_price": round(width, 2), "stops": placed}


async def place_spread_stops(
    ib,
    candidate,
    symbol,
    expiry,
    exchange,
    trading_class,
    underlying_conid,
    underlying_exch,
    account,
    order_ref,
    plans,
):
    """Place conditional close order(s) that buy back the spread when a level is hit.

    One order per plan (verticals: 1; iron condors: 2, OCA-grouped so either breach
    closes the whole position and cancels the sibling). Marketable limit capped at
    the spread width — fills at market but never worse than the defined max loss.
    """
    combo = await _closing_combo(ib, candidate["legs"], symbol, expiry, exchange, trading_class)
    if combo is None:
        return {"ok": False, "error": "Could not qualify legs to build the stop"}

    # Width caps the buy-to-close price: fills at market, never worse than max loss.
    if candidate["strategy"] == "iron_condor":
        width = max(candidate["call_width"], candidate["put_width"])
    else:
        width = candidate["width"]

    return await _place_conditional_closes(
        ib,
        combo,
        width,
        candidate["contracts"],
        plans,
        underlying_conid,
        underlying_exch,
        account,
        order_ref,
    )


def _close_order(qty, order_ref, oca_group, order_type, lmt_price, conditions, account):
    """A buy-to-close order for the reversed combo (one leg of the OCA bracket)."""
    o = Order()
    o.action = "BUY"
    o.orderType = order_type
    o.totalQuantity = qty
    if lmt_price is not None:
        o.lmtPrice = round(lmt_price, 2)
    o.tif = "DAY"
    o.orderRef = order_ref
    o.account = account
    if conditions:
        o.conditions = conditions
        o.conditionsIgnoreRth = True
    if oca_group:
        o.ocaGroup = oca_group
        o.ocaType = 1  # first fill cancels the rest of the bracket
    return o


async def place_spread_bracket(
    ib,
    candidate,
    symbol,
    expiry,
    exchange,
    trading_class,
    underlying_conid,
    underlying_exch,
    account,
    order_ref,
    plans,
    *,
    credit,
    target_frac,
    time_cutoff,
):
    """Place the full exit bracket on a filled spread as one OCA group.

    - Profit target: resting buy-to-close LMT at (1 - target_frac) × credit.
    - Stop(s): price-conditional marketable limit(s) capped at the spread width.
    - Time exit: time-conditional marketable limit at `time_cutoff`.

    All share one OCA group, so whichever fills first cancels the others (server-side).
    The profit target naturally captures near-worthless winners well before the timer.
    """
    combo = await _closing_combo(ib, candidate["legs"], symbol, expiry, exchange, trading_class)
    if combo is None:
        return {"ok": False, "error": "Could not qualify legs to build the bracket"}

    if candidate["strategy"] == "iron_condor":
        width = max(candidate["call_width"], candidate["put_width"])
    else:
        width = candidate["width"]
    qty = candidate["contracts"]
    oca = order_ref  # one OCA group for the whole bracket

    result = {
        "ok": True,
        "oca_group": oca,
        "limit_price": round(width, 2),
        "profit_target": None,
        "stops": [],
        "time_exit": None,
    }

    if target_frac and credit and credit > 0:
        target_debit = max(0.01, round((1 - target_frac) * credit, 2))
        order = _close_order(qty, order_ref, oca, "LMT", target_debit, None, account)
        trade = ib.placeOrder(combo, order)
        result["profit_target"] = {
            "order_id": trade.order.orderId,
            "limit_debit": target_debit,
            "capture_frac": target_frac,
        }

    for plan in plans:
        cond = PriceCondition()
        cond.conId = underlying_conid
        cond.exch = underlying_exch
        cond.isMore = plan["is_more"]
        cond.price = plan["trigger"]
        order = _close_order(qty, order_ref, oca, "LMT", width, [cond], account)
        trade = ib.placeOrder(combo, order)
        result["stops"].append(
            {
                "side": plan["side"],
                "order_id": trade.order.orderId,
                "trigger": plan["trigger"],
                "is_more": plan["is_more"],
                "binding": plan["binding"],
                "levels": plan["levels"],
            }
        )

    if time_cutoff:
        tcond = TimeCondition()
        tcond.time = time_cutoff
        tcond.isMore = True  # trigger once the clock passes the cutoff
        order = _close_order(qty, order_ref, oca, "LMT", width, [tcond], account)
        trade = ib.placeOrder(combo, order)
        result["time_exit"] = {
            "order_id": trade.order.orderId,
            "cutoff": time_cutoff,
            "limit_price": round(width, 2),
        }

    await asyncio.sleep(2)
    return result


async def emergency_close(
    ib, candidate, symbol, expiry, exchange, trading_class, account, order_ref
):
    """Immediately market-close the spread (used if a stop fails after the entry filled)."""
    combo = await _closing_combo(ib, candidate["legs"], symbol, expiry, exchange, trading_class)
    if combo is None:
        return {"ok": False, "error": "Could not qualify legs for emergency close"}
    order = Order()
    order.action = "BUY"
    order.orderType = "MKT"
    order.totalQuantity = candidate["contracts"]
    order.tif = "DAY"
    order.orderRef = order_ref
    order.account = account
    trade = ib.placeOrder(combo, order)
    await asyncio.sleep(2)
    return {"ok": True, "order_id": trade.order.orderId, "status": trade.orderStatus.status}


# --------------------------------------------------------------------------- #
# Verify / repair stops on open 0DTE positions
# --------------------------------------------------------------------------- #
def _today_ny() -> str:
    return datetime.now(_NY).strftime("%Y%m%d")


def reconstruct_spread(legs: list[dict]):
    """Rebuild a spread candidate from IB position legs (right/strike/qty/conId).

    Recognizes a 2-leg vertical (bear call / bull put) or a 4-leg iron condor.
    Returns a candidate dict (with _close_conids and _width_cap for placement) or
    None when the legs don't form a recognized 0DTE credit spread.
    """
    calls = sorted((leg for leg in legs if leg["right"] == "C"), key=lambda x: x["strike"])
    puts = sorted((leg for leg in legs if leg["right"] == "P"), key=lambda x: x["strike"])

    def view(leg):
        return {
            "action": "sell" if leg["qty"] < 0 else "buy",
            "right": leg["right"],
            "strike": leg["strike"],
        }

    def closers(ls):
        # Close = reverse: short leg (qty<0) → BUY back, long leg (qty>0) → SELL.
        return [(leg["conId"], "BUY" if leg["qty"] < 0 else "SELL") for leg in ls]

    if len(calls) == 2 and not puts:
        short, long = calls[0], calls[1]  # bear call: short is the lower strike
        if short["qty"] >= 0 or long["qty"] <= 0:
            return None
        width = abs(long["strike"] - short["strike"])
        return {
            "strategy": "bear_call",
            "legs": [view(short), view(long)],
            "width": width,
            "contracts": abs(short["qty"]),
            "net_credit": 0.0,
            "_close_conids": closers([short, long]),
            "_width_cap": width,
        }
    if len(puts) == 2 and not calls:
        long, short = puts[0], puts[1]  # bull put: short is the higher strike
        if short["qty"] >= 0 or long["qty"] <= 0:
            return None
        width = abs(short["strike"] - long["strike"])
        return {
            "strategy": "bull_put",
            "legs": [view(short), view(long)],
            "width": width,
            "contracts": abs(short["qty"]),
            "net_credit": 0.0,
            "_close_conids": closers([short, long]),
            "_width_cap": width,
        }
    if len(calls) == 2 and len(puts) == 2:
        call_short, call_long = calls[0], calls[1]
        put_long, put_short = puts[0], puts[1]
        cw = abs(call_long["strike"] - call_short["strike"])
        pw = abs(put_short["strike"] - put_long["strike"])
        return {
            "strategy": "iron_condor",
            "legs": [view(put_short), view(put_long), view(call_short), view(call_long)],
            "call_width": cw,
            "put_width": pw,
            "contracts": abs(call_short["qty"]),
            "net_credit": 0.0,
            "_close_conids": closers([put_short, put_long, call_short, call_long]),
            "_width_cap": max(cw, pw),
        }
    return None


async def verify_zdte_stops(port: int = 7497, account: str | None = None, repair: bool = False):
    """Check that every open 0DTE credit spread has a resting protective stop.

    Reports protected / unprotected / unrecognized positions. With repair=True,
    places a strike-level stop (± the symbol's preset buffer) on any unprotected
    recognized spread — a safety net that needs no live market data.
    """
    # Lazy import avoids a circular dependency (zero_dte imports this module).
    from trading_skills.broker.zero_dte import INDEX_SPECS, resolve_underlying

    try:
        async with ib_connection(port, CLIENT_IDS["zero_dte"], readonly=not repair) as ib:
            managed = ib.managedAccounts()
            if account and managed and account not in managed:
                return {
                    "success": False,
                    "error": f"Account {account} not found. Available: {managed}",
                }

            today = _today_ny()
            raw = await fetch_positions(ib, account=account)

            await fetch_with_timeout(ib.reqAllOpenOrdersAsync(), timeout=5, default=[])
            protected = set()
            for t in ib.openTrades():
                ref = t.order.orderRef or ""
                if ref.startswith("ZDTE_STOP_") and t.orderStatus.status in _ACTIVE_STOP_STATUSES:
                    parts = ref.split("_")
                    if len(parts) >= 2:  # ...._<symbol>_<expiry>
                        protected.add(((t.order.account or ""), parts[-2]))

            groups: dict = {}
            for p in raw:
                c = p.contract
                if c.secType != "OPT" or p.position == 0:
                    continue
                if c.lastTradeDateOrContractMonth != today:
                    continue  # 0DTE only
                groups.setdefault((p.account, c.symbol), []).append(
                    {"right": c.right, "strike": c.strike, "qty": p.position, "conId": c.conId}
                )

            report = {
                "success": True,
                "today": today,
                "positions_checked": len(groups),
                "protected": [],
                "unprotected": [],
                "repaired": [],
                "unrecognized": [],
            }
            for (acct, symbol), legs in groups.items():
                cand = reconstruct_spread(legs)
                base = {
                    "account": acct,
                    "symbol": symbol,
                    "strategy": cand["strategy"] if cand else "unrecognized",
                    "contracts": cand["contracts"] if cand else None,
                }
                if cand is None:
                    report["unrecognized"].append({**base, "legs": legs})
                elif (acct, symbol) in protected:
                    report["protected"].append(base)
                elif not repair:
                    report["unprotected"].append(base)
                else:
                    stop = await _repair_stop(
                        ib, cand, symbol, acct, today, INDEX_SPECS, resolve_underlying
                    )
                    report["repaired"].append({**base, "stop": stop})
            return report
    except ConnectionError as e:
        return {"success": False, "error": str(e)}


async def _repair_stop(ib, cand, symbol, account, today, index_specs, resolve_underlying):
    """Place a strike-level stop on a reconstructed spread (no market data needed)."""
    und, _sec, _at = resolve_underlying(symbol)
    qualified = await fetch_with_timeout(ib.qualifyContractsAsync(und), timeout=10, default=[])
    if not qualified or not qualified[0].conId:
        return {"ok": False, "error": f"Could not qualify underlying {symbol}"}
    underlying_exch = index_specs.get(symbol.upper(), "SMART")
    buf = STOP_PRESETS.get(symbol.upper(), STOP_PRESETS["_default"])["buffer"]
    # Strike-level only (mult=0, no delta) so no spot/IV lookup is required.
    plans = stop_plan(cand, 0.0, 0.0, 0.045, mult=0, buffer_pts=buf, target_delta=None)
    combo = _closing_combo_from_conids(symbol, "SMART", cand["_close_conids"])
    order_ref = f"ZDTE_STOP_{cand['strategy']}_{symbol}_{today}"
    return await _place_conditional_closes(
        ib,
        combo,
        cand["_width_cap"],
        cand["contracts"],
        plans,
        und.conId,
        underlying_exch,
        account,
        order_ref,
    )

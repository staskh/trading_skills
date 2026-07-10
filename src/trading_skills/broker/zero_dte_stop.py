# ABOUTME: Stop-loss placement for 0DTE credit spreads — level-anchored conditional close orders.
# ABOUTME: Triggers on the underlying (short strike / premium cap / delta) and buys back the combo.

import asyncio

from ib_async import ComboLeg, Contract, Option, Order, PriceCondition

from trading_skills.black_scholes import black_scholes_delta, black_scholes_price
from trading_skills.utils import fetch_with_timeout

# Close at 2x the credit received (loss = 1x credit) unless overridden.
DEFAULT_STOP_MULT = 2.0


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
        order.totalQuantity = candidate["contracts"]
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

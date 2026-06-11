# ABOUTME: Stop-loss management for PMCC, naked LEAPS, and stock positions in IB.
# ABOUTME: Downside protection: stop price calculation, alerts, and conditional order management.

import asyncio

from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_positions,
    fetch_spot_prices,
    ib_connection,
    normalize_positions,
)
from trading_skills.broker.pmcc_advisor import get_option_price
from trading_skills.utils import (
    fetch_with_timeout,
    generated_at_str,
    is_trading_now,
)

# OrderRef prefix for stop-loss orders placed by this module
_SL_PREFIX = "SL_"
_SL_FALL_PREFIX = "SL_FALL_"
_MODULE_PREFIXES = (_SL_PREFIX,)


# ===========================================================================
# ANALYTICS (no IBKR dependency — fully testable in isolation)
# ===========================================================================


def calc_stop_basis(
    current_mid: float | None,
    avg_cost: float,
    forced: bool = False,
) -> float:
    """Reference basis for stop price calculation.

    Normal: max(current_mid, avg_cost) — ratchets up, never down.
    Forced: current_mid — anchored to today's price, can be lower than avg_cost.
    Falls back to avg_cost when current_mid is unavailable in either mode.
    """
    has_mid = current_mid is not None and current_mid > 0
    if forced:
        return current_mid if has_mid else avg_cost
    return max(current_mid, avg_cost) if has_mid else avg_cost


def calc_stop_price(
    current_mid: float | None,
    avg_cost: float,
    stop_pct: float,
    forced: bool = False,
) -> float:
    """Stop trigger price = basis × (1 - stop_pct/100)."""
    basis = calc_stop_basis(current_mid, avg_cost, forced)
    return round(basis * (1.0 - stop_pct / 100.0), 2)


def calc_short_premium_decay_pct(
    premium_received: float,
    current_price: float,
) -> float:
    """Percentage of short premium already captured (0 = intact, 100 = fully decayed)."""
    if premium_received <= 0:
        return 0.0
    return ((premium_received - current_price) / premium_received) * 100.0


def parse_legs_spec(legs: list[str] | None) -> set[tuple[str, float, str, str]] | None:
    """Parse leg specs like 'IBKR:70C:20270115' into (sym, strike, expiry, right) tuples.

    Format: SYMBOL:STRIKE[C|P]:EXPIRY. Right is the last char of the strike token
    and defaults to C if omitted. Expiry is YYYYMMDD.
    Returns None for None/empty input. Raises ValueError on malformed input.
    """
    if not legs:
        return None
    out: set[tuple[str, float, str, str]] = set()
    for spec in legs:
        parts = spec.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid leg spec {spec!r}: expected SYMBOL:STRIKE[C|P]:EXPIRY")
        sym, strike_right, expiry = parts
        strike_right = strike_right.upper()
        if strike_right and strike_right[-1] in ("C", "P"):
            right = strike_right[-1]
            strike_str = strike_right[:-1]
        else:
            right = "C"
            strike_str = strike_right
        try:
            strike = float(strike_str)
        except ValueError as e:
            raise ValueError(f"Invalid strike in leg spec {spec!r}") from e
        if len(expiry) != 8 or not expiry.isdigit():
            raise ValueError(f"Invalid expiry in leg spec {spec!r}: expected YYYYMMDD")
        out.add((sym.upper(), strike, expiry, right))
    return out


def calc_pmcc_bag_qty(leaps_qty: int, short_qtys: list[int]) -> int:
    """Bag order quantity for a PMCC = the smallest leg (limiting leg).

    A 1:1 combo (1 LEAPS + 1 of each short) of size N closes N LEAPS plus N of
    each short. If any leg has fewer than N contracts, the order would fail or
    fill partially at trigger time. So bag qty = min(leaps_qty, *short_qtys).
    If no shorts, returns leaps_qty (caller shouldn't be using this for non-PMCC).
    """
    if not short_qtys:
        return leaps_qty
    return min(leaps_qty, *short_qtys)


def filter_normalized_by_legs(
    normalized: list[dict],
    legs_set: set[tuple[str, float, str, str]],
) -> list[dict]:
    """Keep only OPT positions whose (symbol, strike, expiry, right) matches a leg.

    Stocks are dropped (legs filter is option-specific).
    """
    out = []
    for pos in normalized:
        if pos["sec_type"] != "OPT":
            continue
        key = (pos["symbol"].upper(), pos["strike"], pos["expiry"], pos["right"])
        if key in legs_set:
            out.append(pos)
    return out


def identify_positions(normalized: list[dict]) -> list[dict]:
    """Classify normalized IB positions into pmcc, leaps, and stock groups.

    Groups positions by (account, symbol). For each group:
    - Long options with matching shorts on the same symbol → pmcc (longest-dated long is the LEAPS)
    - Long options without matching shorts → leaps
    - Positive stock positions → stock
    Short-only and negative stock positions are ignored.
    """
    positions = []

    by_key: dict[tuple, dict] = {}
    for pos in normalized:
        key = (pos["account"], pos["symbol"])
        if key not in by_key:
            by_key[key] = {"longs": [], "shorts": [], "stocks": []}
        qty = pos["quantity"]
        stype = pos["sec_type"]
        if stype == "STK" and qty > 0:
            by_key[key]["stocks"].append(pos)
        elif stype == "OPT" and qty > 0:
            by_key[key]["longs"].append(pos)
        elif stype == "OPT" and qty < 0:
            by_key[key]["shorts"].append(pos)

    for (account, symbol), group in by_key.items():
        longs = sorted(group["longs"], key=lambda x: x["expiry"], reverse=True)
        shorts = group["shorts"]

        if longs and shorts:
            # Longest-dated long = LEAPS; remaining longs = naked LEAPS
            leaps = longs[0]
            positions.append(
                {
                    "type": "pmcc",
                    "symbol": symbol,
                    "account": account,
                    "qty": int(abs(leaps["quantity"])),
                    "leaps": {
                        "strike": leaps["strike"],
                        "expiry": leaps["expiry"],
                        "right": leaps["right"],
                        "avg_cost": leaps["avg_cost"],
                    },
                    "shorts": [
                        {
                            "strike": s["strike"],
                            "expiry": s["expiry"],
                            "right": s["right"],
                            "premium_received": abs(s["avg_cost"]),
                            "qty": int(abs(s["quantity"])),
                        }
                        for s in shorts
                    ],
                }
            )
            for long_opt in longs[1:]:
                positions.append(
                    {
                        "type": "leaps",
                        "symbol": symbol,
                        "account": account,
                        "qty": int(abs(long_opt["quantity"])),
                        "leaps": {
                            "strike": long_opt["strike"],
                            "expiry": long_opt["expiry"],
                            "right": long_opt["right"],
                            "avg_cost": long_opt["avg_cost"],
                        },
                    }
                )
        else:
            for long_opt in longs:
                positions.append(
                    {
                        "type": "leaps",
                        "symbol": symbol,
                        "account": account,
                        "qty": int(abs(long_opt["quantity"])),
                        "leaps": {
                            "strike": long_opt["strike"],
                            "expiry": long_opt["expiry"],
                            "right": long_opt["right"],
                            "avg_cost": long_opt["avg_cost"],
                        },
                    }
                )

        for stock in group["stocks"]:
            positions.append(
                {
                    "type": "stock",
                    "symbol": symbol,
                    "account": account,
                    "qty": int(abs(stock["quantity"])),
                    "avg_cost": stock["avg_cost"],
                }
            )

    return positions


def _sl_fall_key(position: dict) -> str:
    """Position key embedded in SL_FALL_ order refs."""
    if position["type"] in ("pmcc", "leaps"):
        leaps = position["leaps"]
        return f"{position['symbol']}_{leaps['strike']}_{leaps['expiry']}"
    return f"{position['symbol']}_STK"


def _stop_action(
    new_stop: float,
    existing_stop: float | None,
    forced: bool,
) -> str:
    """Decide what stop action to take for a falling-stop order.

    Returns: 'place_new' | 'preserve_existing' | 'overwrite'
    A higher stop price is more protective (fires sooner as price falls).
    """
    if existing_stop is None:
        return "place_new"
    if existing_stop >= new_stop:
        return "overwrite" if forced else "preserve_existing"
    return "place_new"


def build_position_analysis(
    position: dict,
    underlying_price: float,
    current_mid: float | None,
    short_mids: list[float | None],
    existing_stop: float | None,
    stop_pct: float,
    forced: bool,
    short_near_strike_pct: float = 5.0,
) -> dict:
    """Compute full stop-loss analysis for one position (pmcc / leaps / stock)."""
    ptype = position["type"]
    symbol = position["symbol"]
    qty = position["qty"]

    if ptype in ("pmcc", "leaps"):
        avg_cost = position["leaps"]["avg_cost"]
    else:
        avg_cost = position["avg_cost"]

    basis = calc_stop_basis(current_mid, avg_cost, forced)
    stop_price = round(basis * (1.0 - stop_pct / 100.0), 2)
    loss_pct = round((1.0 - current_mid / basis) * 100.0, 1) if current_mid and basis > 0 else None

    if current_mid is not None and current_mid <= stop_price:
        stop_act = "price_below_stop"
    else:
        stop_act = _stop_action(stop_price, existing_stop, forced)
    early_warning_pct = stop_pct / 2.0
    alert_soon = loss_pct is not None and loss_pct >= early_warning_pct

    alerts = []
    if ptype in ("pmcc", "leaps") and loss_pct is not None and alert_soon:
        alerts.append(
            {
                "type": "leaps_early_warning",
                "message": (
                    f"LEAPS down {loss_pct:.1f}% from basis ${basis:.2f} "
                    f"(stop at {stop_pct:.0f}%, warning at {early_warning_pct:.0f}%)"
                ),
                "current_loss_pct": loss_pct,
                "threshold_pct": early_warning_pct,
                "basis": round(basis, 2),
            }
        )

    if ptype == "pmcc":
        for i, short in enumerate(position["shorts"]):
            sp = short_mids[i] if i < len(short_mids) else None
            if sp is not None:
                decay = calc_short_premium_decay_pct(short["premium_received"], sp)
                if decay >= 90.0:
                    alerts.append(
                        {
                            "type": "short_premium_decay",
                            "message": (
                                f"Short {short['strike']} {short['expiry']}: "
                                f"{decay:.1f}% premium captured — close or roll"
                            ),
                            "decay_pct": round(decay, 1),
                            "threshold_pct": 90.0,
                        }
                    )

        for short in position["shorts"]:
            gap_pct = (short["strike"] - underlying_price) / short["strike"] * 100.0
            if gap_pct <= short_near_strike_pct:
                direction = "above" if underlying_price >= short["strike"] else "below"
                alerts.append(
                    {
                        "type": "short_near_strike",
                        "message": (
                            f"Spot ${underlying_price:.2f} is {abs(gap_pct):.1f}% {direction} "
                            f"short strike ${short['strike']:.2f} "
                            f"(threshold {short_near_strike_pct:.0f}%)"
                        ),
                        "gap_pct": round(gap_pct, 1),
                        "threshold_pct": short_near_strike_pct,
                    }
                )

    result: dict = {
        "symbol": symbol,
        "type": ptype,
        "account": position["account"],
        "qty": qty,
        "underlying_price": round(underlying_price, 2),
        "stop_loss": {
            "stop_price": stop_price,
            "action": stop_act,
            "existing_stop": existing_stop,
        },
        "alert_soon": alert_soon,
        "alerts": alerts,
    }

    if ptype in ("pmcc", "leaps"):
        result["leaps"] = {
            "strike": position["leaps"]["strike"],
            "expiry": position["leaps"]["expiry"],
            "right": position["leaps"]["right"],
            "avg_cost": avg_cost,
            "current_price": round(current_mid, 2) if current_mid is not None else None,
            "stop_basis": round(basis, 2),
            "stop_price": stop_price,
            "loss_pct": loss_pct,
        }

    if ptype == "pmcc":
        shorts_out = []
        for i, short in enumerate(position["shorts"]):
            sp = short_mids[i] if i < len(short_mids) else None
            decay = (
                round(calc_short_premium_decay_pct(short["premium_received"], sp), 1)
                if sp is not None
                else None
            )
            shorts_out.append(
                {
                    "strike": short["strike"],
                    "expiry": short["expiry"],
                    "right": short["right"],
                    "qty": short["qty"],
                    "premium_received": short["premium_received"],
                    "current_price": round(sp, 2) if sp is not None else None,
                    "decay_pct": decay,
                }
            )
        result["shorts"] = shorts_out
        result["bag_qty"] = calc_pmcc_bag_qty(qty, [s["qty"] for s in position["shorts"]])

    if ptype == "stock":
        result["stock"] = {
            "avg_cost": avg_cost,
            "stop_basis": round(basis, 2),
            "stop_price": stop_price,
            "loss_pct": loss_pct,
        }

    return result


def filter_orders_by_account(orders: list[dict], accounts: list[str]) -> list[dict]:
    """Keep only orders whose ``account`` field matches one of the given accounts.

    Used to scope orphan detection to the queried account(s) so that SL_ orders in
    other accounts are not incorrectly cancelled when running with ``--account``.
    Orders missing or with an empty ``account`` field are excluded.
    """
    accounts_set = {a for a in accounts if a}
    return [o for o in orders if o.get("account") in accounts_set]


def detect_orphan_orders(
    open_orders: list[dict],
    active_positions: list[dict],
) -> list[dict]:
    """Find SL_FALL_ orders with no matching active position.

    Matching is account-aware: an order in account A only matches a position in
    account A, even when the same {symbol, strike, expiry} exists in another
    account. Without this, a true orphan in one account would be hidden by a
    lookalike position in another when multiple accounts are queried at once.
    """
    active_keys: set[tuple[str, str]] = {
        (p.get("account", "") or "", _sl_fall_key(p)) for p in active_positions
    }

    orphans = []
    for order in open_orders:
        ref = order.get("order_ref", "")
        if not ref.startswith(_SL_FALL_PREFIX):
            continue
        key = ref[len(_SL_FALL_PREFIX) :]
        account = order.get("account", "") or ""
        if (account, key) not in active_keys:
            orphans.append(order)
    return orphans


def summarize_all_conditional_orders(open_orders: list[dict]) -> dict:
    """Split all conditional IB orders into module-managed and manually placed.

    Only orders that have at least one condition are included.
    Module orders have refs starting with SL_.
    """
    module_orders: list[dict] = []
    manual_orders: list[dict] = []
    for order in open_orders:
        if not order.get("conditions"):
            continue
        ref = order.get("order_ref", "")
        if any(ref.startswith(p) for p in _MODULE_PREFIXES):
            module_orders.append(order)
        else:
            manual_orders.append(order)
    return {"module": module_orders, "manual": manual_orders}


# ===========================================================================
# IBKR DATA LAYER
# ===========================================================================


async def _fetch_open_orders(ib) -> list[dict]:
    """Fetch all open orders from IB, normalized to plain dicts."""
    await fetch_with_timeout(ib.reqAllOpenOrdersAsync(), timeout=5, default=[])
    trades = ib.openTrades()
    result = []
    for trade in trades:
        c = trade.contract
        o = trade.order
        conditions = getattr(o, "conditions", []) or []
        condition_prices = []
        for cond in conditions:
            p = getattr(cond, "price", None)
            is_more = getattr(cond, "isMore", None)
            if p is not None:
                condition_prices.append({"price": p, "is_more": is_more})
        result.append(
            {
                "order_id": o.orderId,
                "order_ref": getattr(o, "orderRef", "") or "",
                "account": getattr(o, "account", "") or "",
                "action": o.action,
                "order_type": o.orderType,
                "qty": o.totalQuantity,
                "symbol": c.symbol,
                "sec_type": c.secType,
                "strike": getattr(c, "strike", None),
                "expiry": getattr(c, "lastTradeDateOrContractMonth", None),
                "right": getattr(c, "right", None),
                "conditions": condition_prices,
            }
        )
    return result


def _parse_existing_stops(open_orders: list[dict]) -> dict[tuple[str, str], float]:
    """Extract existing SL_FALL_ stop prices keyed by (account, position key).

    Returns {(account, position_key): highest_stop_price}.
    A higher stop price is more protective; keep the max if duplicates exist.
    Account is part of the key so that a SL_FALL_ on the same {symbol, strike,
    expiry} in a different account does not leak its stop price into this
    account's analysis when multiple accounts are queried at once.
    """
    stops: dict[tuple[str, str], float] = {}
    for order in open_orders:
        ref = order.get("order_ref", "")
        if not ref.startswith(_SL_FALL_PREFIX):
            continue
        key = ref[len(_SL_FALL_PREFIX) :]
        account = order.get("account", "") or ""
        conditions = order.get("conditions", [])
        if not conditions:
            continue
        price = conditions[0]["price"]
        composite = (account, key)
        if composite not in stops or price > stops[composite]:
            stops[composite] = price
    return stops


async def _cancel_orphan_orders(ib, orphan_orders: list[dict]) -> list[dict]:
    """Cancel all orphan SL_ orders in IB."""
    trades_by_id = {t.order.orderId: t for t in ib.openTrades()}
    results = []
    for orphan in orphan_orders:
        oid = orphan.get("order_id")
        if oid and oid in trades_by_id:
            ib.cancelOrder(trades_by_id[oid].order)
            results.append({"order_id": oid, "order_ref": orphan["order_ref"], "cancelled": True})
        else:
            results.append(
                {
                    "order_id": oid,
                    "order_ref": orphan["order_ref"],
                    "cancelled": False,
                    "error": "order not found in open trades",
                }
            )
    return results


async def _place_combo_stop_order(
    ib,
    position: dict,
    qty: int,
    condition_con_id: int,
    condition_price: float,
    order_ref: str,
) -> dict:
    """Place a single combo (BAG) stop order closing LEAPS + all shorts atomically."""
    from ib_async import ComboLeg, Contract, Option, Order, PriceCondition

    symbol = position["symbol"]
    leaps = position["leaps"]
    shorts = position["shorts"]

    leaps_contract = Option(symbol, leaps["expiry"], leaps["strike"], leaps["right"], "SMART")
    short_contracts = [
        Option(symbol, s["expiry"], s["strike"], s["right"], "SMART") for s in shorts
    ]
    all_contracts = [leaps_contract] + short_contracts

    qualified = await fetch_with_timeout(
        ib.qualifyContractsAsync(*all_contracts), timeout=15, default=[]
    )
    if len(qualified) < len(all_contracts):
        return {"ok": False, "error": f"Could not qualify all legs for {symbol}"}

    legs = []
    leaps_leg = ComboLeg()
    leaps_leg.conId = qualified[0].conId
    leaps_leg.ratio = 1
    leaps_leg.action = "BUY"
    leaps_leg.exchange = "SMART"
    legs.append(leaps_leg)

    for qc in qualified[1:]:
        short_leg = ComboLeg()
        short_leg.conId = qc.conId
        short_leg.ratio = 1
        short_leg.action = "SELL"
        short_leg.exchange = "SMART"
        legs.append(short_leg)

    combo = Contract()
    combo.symbol = symbol
    combo.secType = "BAG"
    combo.currency = "USD"
    combo.exchange = "SMART"
    combo.comboLegs = legs

    condition = PriceCondition()
    condition.conId = condition_con_id
    condition.exch = "SMART"
    condition.isMore = False
    condition.price = condition_price

    order = Order()
    order.action = "SELL"
    order.orderType = "MKT"
    order.totalQuantity = qty
    order.conditions = [condition]
    order.conditionsIgnoreRth = True
    order.orderRef = order_ref
    order.tif = "GTC"
    # Pin order to the position's account so IB routes execution to the account
    # that actually holds the legs. Without this, multi-account connections
    # default to a single account and the conditional order fails at trigger.
    if position.get("account"):
        order.account = position["account"]

    trade = ib.placeOrder(combo, order)
    return {"ok": True, "order_id": trade.order.orderId, "order_ref": order_ref}


async def _place_simple_stop_order(
    ib,
    position: dict,
    qty: int,
    condition_con_id: int,
    condition_price: float,
    order_ref: str,
) -> dict:
    """Place a single stop order for a naked LEAPS or stock position."""
    from ib_async import Option, Order, PriceCondition, Stock

    symbol = position["symbol"]
    ptype = position["type"]

    if ptype == "leaps":
        leaps = position["leaps"]
        contract = Option(symbol, leaps["expiry"], leaps["strike"], leaps["right"], "SMART")
    else:
        contract = Stock(symbol, "SMART", "USD")

    qualified = await fetch_with_timeout(ib.qualifyContractsAsync(contract), timeout=10, default=[])
    if not qualified:
        return {"ok": False, "error": f"Could not qualify {symbol}"}

    condition = PriceCondition()
    condition.conId = condition_con_id
    condition.exch = "SMART"
    condition.isMore = False
    condition.price = condition_price

    order = Order()
    order.action = "SELL"
    order.orderType = "MKT"
    order.totalQuantity = qty
    order.conditions = [condition]
    order.conditionsIgnoreRth = True
    order.orderRef = order_ref
    order.tif = "GTC"
    if position.get("account"):
        order.account = position["account"]

    trade = ib.placeOrder(qualified[0], order)
    return {"ok": True, "order_id": trade.order.orderId, "order_ref": order_ref}


async def _execute_position_stop(
    ib,
    analysis: dict,
    leaps_con_id: int | None,
    stock_con_id: int | None,
    open_orders: list[dict] | None = None,
) -> dict:
    """Place the stop-loss order for one position based on analysis.

    On overwrite: cancels the existing order before placing the new one.
    """
    ptype = analysis["type"]
    symbol = analysis["symbol"]
    qty = analysis["qty"]
    stop_price = analysis["stop_loss"]["stop_price"]
    action = analysis["stop_loss"]["action"]

    if action not in ("place_new", "overwrite"):
        return {"symbol": symbol, "skipped": True, "reason": action}

    order_ref = f"{_SL_FALL_PREFIX}{_sl_fall_key(analysis)}"
    position_account = analysis.get("account") or ""

    if open_orders:
        trades_by_id = {t.order.orderId: t for t in ib.openTrades()}
        for o in open_orders:
            # Only cancel the prior SL_FALL_ order that we'd be replacing: same
            # order_ref AND same account. Symbol-only matching cancels orders on
            # the same underlying in *other* accounts, and matching any
            # conditional order would wipe manual orders too.
            if o.get("order_ref") != order_ref:
                continue
            if (o.get("account") or "") != position_account:
                continue
            oid = o.get("order_id")
            if oid and oid in trades_by_id:
                ib.cancelOrder(trades_by_id[oid].order)

    if ptype == "pmcc":
        if not leaps_con_id:
            return {"symbol": symbol, "ok": False, "error": "no LEAPS conId"}
        # Bag order qty is bounded by the limiting leg. If LEAPS qty > shorts,
        # the bag must size to shorts or it will fail / fill partially at trigger.
        short_qtys = [s["qty"] for s in analysis.get("shorts", [])]
        bag_qty = calc_pmcc_bag_qty(qty, short_qtys)
        return await _place_combo_stop_order(
            ib=ib,
            position=analysis,
            qty=bag_qty,
            condition_con_id=leaps_con_id,
            condition_price=stop_price,
            order_ref=order_ref,
        )
    elif ptype == "leaps":
        if not leaps_con_id:
            return {"symbol": symbol, "ok": False, "error": "no LEAPS conId"}
        return await _place_simple_stop_order(
            ib=ib,
            position=analysis,
            qty=qty,
            condition_con_id=leaps_con_id,
            condition_price=stop_price,
            order_ref=order_ref,
        )
    else:  # stock
        if not stock_con_id:
            return {"symbol": symbol, "ok": False, "error": "no stock conId"}
        return await _place_simple_stop_order(
            ib=ib,
            position=analysis,
            qty=qty,
            condition_con_id=stock_con_id,
            condition_price=stop_price,
            order_ref=order_ref,
        )


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================


async def get_stop_loss_data(
    port: int = 7496,
    account: str | None = None,
    symbols: list[str] | None = None,
    legs: list[str] | None = None,
    stop_pct: float = 40.0,
    short_near_strike_pct: float = 5.0,
    price_mode: str = "mid",
    dry_run: bool = True,
    forced: bool = False,
) -> dict:
    """Analyze positions and manage downside stop-loss orders.

    dry_run=True (default): analyze and report; no orders placed (still connects to IB
        to fetch positions/quotes).
    dry_run=False (--execute): cancel orphan orders, place SL_ conditional orders.
    forced=True: basis = current_mid_price (can lower existing stops).
    legs: list of SYMBOL:STRIKE[C|P]:EXPIRY specs. Narrows analysis to those
    option legs only (takes precedence over ``symbols``). Orphan detection still
    runs against the full position set so unrelated SL_ orders aren't cancelled.
    """
    try:
        legs_set = parse_legs_spec(legs)
        async with ib_connection(port, CLIENT_IDS.get("stop_loss", 14)) as ib:
            ib.reqMarketDataType(4)
            await asyncio.sleep(2)

            managed = ib.managedAccounts()
            if account and account not in managed:
                return {
                    "generated_at": generated_at_str(),
                    "data_delay": "unknown",
                    "error": f"Account {account} not found. Available: {managed}",
                }
            accounts = [account] if account else list(managed)

            # --- Positions ---
            raw = await fetch_positions(ib, account=account)
            normalized = normalize_positions(raw)
            unfiltered_positions = identify_positions(normalized)
            if legs_set:
                # Filter at the leg level (before grouping) so we can target a
                # specific LEAPS/short pair when multiple coexist on the same symbol.
                filtered_normalized = filter_normalized_by_legs(normalized, legs_set)
                all_positions = identify_positions(filtered_normalized)
            elif symbols:
                sym_set = {s.upper() for s in symbols}
                all_positions = [p for p in unfiltered_positions if p["symbol"].upper() in sym_set]
            else:
                all_positions = unfiltered_positions

            # --- Open orders ---
            await asyncio.sleep(1)
            open_orders = await _fetch_open_orders(ib)
            all_conditional_orders = summarize_all_conditional_orders(open_orders)
            # Orphan detection must be scoped to the queried accounts, otherwise SL_
            # orders in other accounts (whose positions aren't loaded here) are
            # incorrectly flagged as orphans and cancelled in execute mode (issue #37).
            account_scoped_orders = filter_orders_by_account(open_orders, accounts)
            orphan_orders = detect_orphan_orders(account_scoped_orders, unfiltered_positions)
            # Existing-stop lookup must also be account-scoped: a SL_FALL_ on the
            # same {symbol, strike, expiry} in a different account is not "our"
            # existing stop and would otherwise leak its price into stop_action.
            existing_stops = _parse_existing_stops(account_scoped_orders)

            if not all_positions:
                return {
                    "generated_at": generated_at_str(),
                    "data_delay": "real-time",
                    "dry_run": dry_run,
                    "forced": forced,
                    "accounts": accounts,
                    "symbols_filter": [s.upper() for s in symbols] if symbols else None,
                    "legs_filter": legs if legs else None,
                    "all_conditional_orders": all_conditional_orders,
                    "orphan_orders": orphan_orders,
                    "alert_soon": [],
                    "positions": [],
                    "message": "No positions found",
                }

            # --- Cancel orphan orders (execute mode only) ---
            cancel_results = []
            if not dry_run and orphan_orders:
                cancel_results = await _cancel_orphan_orders(ib, orphan_orders)

            # --- Fetch market data ---
            unique_symbols = list({p["symbol"] for p in all_positions})
            live = is_trading_now()

            option_positions = [p for p in all_positions if p["type"] in ("pmcc", "leaps")]
            pmcc_positions = [p for p in all_positions if p["type"] == "pmcc"]

            # Option quotes always come from IB: after hours IB still returns the
            # session's last trade, while yfinance can return stale prices from
            # earlier in the day that don't reflect today's market move.
            from trading_skills.broker.pmcc_advisor import _fetch_single_option_quote

            leaps_quote_tasks = [
                _fetch_single_option_quote(
                    ib, pos["symbol"], pos["leaps"]["strike"], pos["leaps"]["expiry"], "C"
                )
                for pos in option_positions
            ]
            short_quote_tasks = [
                _fetch_single_option_quote(ib, pos["symbol"], short["strike"], short["expiry"], "C")
                for pos in pmcc_positions
                for short in pos["shorts"]
            ]

            # Spot: IB while live, yfinance fallback when market is closed and IB
            # bid/ask are unavailable.
            if live:
                spot_task = fetch_spot_prices(ib, unique_symbols)
            else:
                from trading_skills.broker.pmcc_advisor import _fetch_yf_spot_prices

                spot_task = _fetch_yf_spot_prices(unique_symbols)

            results = await asyncio.gather(spot_task, *leaps_quote_tasks, *short_quote_tasks)
            spot_prices: dict[str, float] = results[0]
            leaps_quotes = list(results[1 : 1 + len(option_positions)])
            short_quotes_flat = list(results[1 + len(option_positions) :])

            data_delay = "real-time" if live else "stalled - using last price"
            for q in leaps_quotes:
                if q and q.get("stale"):
                    data_delay = "stalled - using last price"
                    break

            # Map LEAPS quotes back to option_positions by index
            leaps_quote_map: dict[int, dict] = {
                id(pos): leaps_quotes[i] or {} for i, pos in enumerate(option_positions)
            }

            # Map short quotes back to PMCC positions
            short_quote_idx = 0
            short_quote_map: dict[int, list[dict]] = {}
            for pos in pmcc_positions:
                count = len(pos["shorts"])
                short_quote_map[id(pos)] = [
                    short_quotes_flat[short_quote_idx + j] or {} for j in range(count)
                ]
                short_quote_idx += count

            # --- Qualify option contracts for condition conIds (execute mode) ---
            leaps_con_ids: dict[int, int] = {}
            stock_con_ids: dict[str, int] = {}
            if not dry_run:
                from ib_async import Stock

                stock_syms = [p["symbol"] for p in all_positions if p["type"] == "stock"]
                option_syms_for_stock = list(
                    {p["symbol"] for p in all_positions if p["type"] in ("pmcc", "leaps")}
                )
                all_stock_syms = list(set(stock_syms + option_syms_for_stock))

                if all_stock_syms:
                    stock_contracts = [Stock(sym, "SMART", "USD") for sym in all_stock_syms]
                    qs = await fetch_with_timeout(
                        ib.qualifyContractsAsync(*stock_contracts), timeout=15, default=[]
                    )
                    stock_con_ids = {qc.symbol: qc.conId for qc in qs if qc is not None}

                from ib_async import Option as IBOption

                for pos in option_positions:
                    leaps = pos["leaps"]
                    leaps_contract = IBOption(
                        pos["symbol"],
                        leaps["expiry"],
                        leaps["strike"],
                        leaps["right"],
                        "SMART",
                    )
                    ql = await fetch_with_timeout(
                        ib.qualifyContractsAsync(leaps_contract), timeout=10, default=[]
                    )
                    if ql and ql[0] is not None:
                        leaps_con_ids[id(pos)] = ql[0].conId

            # --- Per-position analysis ---
            analyzed_positions = []
            order_results = []

            for pos in all_positions:
                sym = pos["symbol"]
                ptype = pos["type"]
                spot = spot_prices.get(sym)
                if not spot:
                    continue

                if ptype in ("pmcc", "leaps"):
                    lq = leaps_quote_map.get(id(pos), {})
                    current_mid = get_option_price(lq, price_mode)
                    short_mids = [
                        get_option_price(sq, price_mode) for sq in short_quote_map.get(id(pos), [])
                    ]
                else:
                    current_mid = spot
                    short_mids = []

                existing_stop = existing_stops.get(
                    (pos.get("account", "") or "", _sl_fall_key(pos))
                )

                analysis = build_position_analysis(
                    position=pos,
                    underlying_price=spot,
                    current_mid=current_mid,
                    short_mids=short_mids,
                    existing_stop=existing_stop,
                    stop_pct=stop_pct,
                    forced=forced,
                    short_near_strike_pct=short_near_strike_pct,
                )
                analyzed_positions.append(analysis)

                if not dry_run:
                    leaps_con_id = leaps_con_ids.get(id(pos))
                    stock_con_id = stock_con_ids.get(sym)
                    res = await _execute_position_stop(
                        ib=ib,
                        analysis=analysis,
                        leaps_con_id=leaps_con_id,
                        stock_con_id=stock_con_id,
                        open_orders=open_orders,
                    )
                    order_results.append(res)

            if not dry_run and order_results:
                await asyncio.sleep(3)

            alert_soon_symbols = sorted(
                {p["symbol"] for p in analyzed_positions if p["alert_soon"]}
            )

            output = {
                "generated_at": generated_at_str(),
                "data_delay": data_delay,
                "dry_run": dry_run,
                "forced": forced,
                "stop_pct": stop_pct,
                "short_near_strike_pct": short_near_strike_pct,
                "accounts": accounts,
                "symbols_filter": [s.upper() for s in symbols] if symbols else None,
                "legs_filter": legs if legs else None,
                "all_conditional_orders": all_conditional_orders,
                "orphan_orders": orphan_orders,
                "alert_soon": alert_soon_symbols,
                "positions": analyzed_positions,
            }
            if not dry_run:
                output["cancel_results"] = cancel_results
                output["order_results"] = order_results
            return output

    except ValueError as e:
        return {
            "generated_at": generated_at_str(),
            "data_delay": "unknown",
            "error": f"Invalid --legs spec: {e}",
        }
    except ConnectionError as e:
        return {
            "generated_at": generated_at_str(),
            "data_delay": "unknown",
            "error": f"{e}. Is TWS/Gateway running?",
        }

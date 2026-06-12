# ABOUTME: Trailing stop management for naked LEAPS and stock positions in IB.
# ABOUTME: Uses native IB TRAIL orders that auto-track the high. PMCC is out of scope.

import asyncio

from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_positions,
    fetch_spot_prices,
    ib_connection,
    normalize_positions,
)
from trading_skills.broker.pmcc_advisor import get_option_price
from trading_skills.broker.stop_loss import identify_positions
from trading_skills.utils import (
    fetch_with_timeout,
    generated_at_str,
    is_trading_now,
)

# OrderRef prefix for trailing stop orders placed by this module
_TS_PREFIX = "TS_"
_MODULE_PREFIXES = (_TS_PREFIX,)
_TRAIL_ORDER_TYPES = ("TRAIL", "TRAIL LIMIT")


# ===========================================================================
# ANALYTICS (no IBKR dependency — fully testable in isolation)
# ===========================================================================


def calc_trail_reference(
    current_price: float | None,
    avg_cost: float,
    forced: bool = False,
) -> float:
    """Reference price for the initial trail stop.

    Normal: max(current_price, avg_cost) — locks in profit when in profit, never
    starts below entry. IB will then trail upward from there as price climbs.
    Forced: current_price — anchors today's mark regardless of avg_cost (can
    place an initial stop below entry; useful when re-arming after a drawdown).
    Falls back to avg_cost when current_price is unavailable in either mode.
    """
    has_curr = current_price is not None and current_price > 0
    if forced:
        return current_price if has_curr else avg_cost
    return max(current_price, avg_cost) if has_curr else avg_cost


def calc_initial_trail_stop_price(
    reference: float,
    trail_pct: float | None = None,
    trail_amt: float | None = None,
) -> float:
    """Initial trail trigger price below the reference.

    Exactly one of trail_pct or trail_amt must be provided.
    """
    if trail_pct is not None and trail_amt is not None:
        raise ValueError("Specify exactly one of trail_pct or trail_amt, not both")
    if trail_pct is not None:
        return round(reference * (1.0 - trail_pct / 100.0), 2)
    if trail_amt is not None:
        return round(reference - trail_amt, 2)
    raise ValueError("Must specify trail_pct or trail_amt")


def identify_trailable_positions(normalized: list[dict]) -> list[dict]:
    """Stocks and naked LEAPS only. PMCC is excluded.

    PMCC LEAPS get a stop via the combo BAG order in ib-stop-loss; placing a
    standalone TRAIL on the long leg of a PMCC would break the hedge at trigger.
    """
    return [p for p in identify_positions(normalized) if p["type"] in ("stock", "leaps")]


def _ts_key(position: dict) -> str:
    """Position key embedded in TS_ order refs.

    Right is included for options so a long call and long put on the same
    symbol/strike/expiry don't collide and get conflated by existing-order
    detection or overwrite cancellation.
    """
    if position["type"] == "leaps":
        leaps = position["leaps"]
        return f"{position['symbol']}_{leaps['strike']}_{leaps['expiry']}_{leaps['right']}"
    return f"{position['symbol']}_STK"


def _trail_action(existing_trail: dict | None, forced: bool) -> str:
    """Decide what action to take for a trailing stop order.

    Returns: 'place_new' | 'preserve_existing' | 'overwrite'

    TRAIL orders are server-side ratchets — IB has been tracking the high since
    placement. Replacing one resets that high to today's reference, which can
    *lower* the effective stop. So we default to preserve when one exists, and
    require --forced to explicitly cancel and replace with current parameters.
    """
    if existing_trail is None:
        return "place_new"
    return "overwrite" if forced else "preserve_existing"


def build_trail_analysis(
    position: dict,
    underlying_price: float,
    current_price: float | None,
    existing_trail: dict | None,
    trail_pct: float | None,
    trail_amt: float | None,
    forced: bool,
) -> dict:
    """Compute trailing stop analysis for one position (leaps or stock)."""
    ptype = position["type"]
    symbol = position["symbol"]
    qty = position["qty"]

    if ptype == "leaps":
        avg_cost = position["leaps"]["avg_cost"]
    else:
        avg_cost = position["avg_cost"]

    reference = calc_trail_reference(current_price, avg_cost, forced)
    initial_stop = calc_initial_trail_stop_price(reference, trail_pct, trail_amt)
    action = _trail_action(existing_trail, forced)

    result: dict = {
        "symbol": symbol,
        "type": ptype,
        "account": position["account"],
        "qty": qty,
        "underlying_price": round(underlying_price, 2),
        "trail_stop": {
            "trail_pct": trail_pct,
            "trail_amt": trail_amt,
            "reference": round(reference, 2),
            "initial_stop_price": initial_stop,
            "action": action,
            "existing_trail": existing_trail,
        },
    }

    if ptype == "leaps":
        result["leaps"] = {
            "strike": position["leaps"]["strike"],
            "expiry": position["leaps"]["expiry"],
            "right": position["leaps"]["right"],
            "avg_cost": avg_cost,
            "current_price": round(current_price, 2) if current_price is not None else None,
        }
    else:
        result["stock"] = {
            "avg_cost": avg_cost,
            "current_price": round(current_price, 2) if current_price is not None else None,
        }

    return result


def filter_orders_by_account(orders: list[dict], accounts: list[str]) -> list[dict]:
    """Keep only orders whose account matches one of the given accounts.

    Scopes orphan / existing-trail detection to the queried accounts so that
    TS_ orders in unrelated accounts aren't touched.
    """
    accounts_set = {a for a in accounts if a}
    return [o for o in orders if o.get("account") in accounts_set]


def detect_orphan_trail_orders(
    open_orders: list[dict],
    active_positions: list[dict],
) -> list[dict]:
    """Find TS_ TRAIL orders with no matching active position.

    Matching is account-aware: an order in account A only matches a position in
    the same account.
    """
    active_keys: set[tuple[str, str]] = {
        (p.get("account", "") or "", _ts_key(p)) for p in active_positions
    }

    orphans = []
    for order in open_orders:
        ref = order.get("order_ref", "")
        if not ref.startswith(_TS_PREFIX):
            continue
        if order.get("order_type") not in _TRAIL_ORDER_TYPES:
            continue
        key = ref[len(_TS_PREFIX) :]
        account = order.get("account", "") or ""
        if (account, key) not in active_keys:
            orphans.append(order)
    return orphans


def summarize_all_trail_orders(open_orders: list[dict]) -> dict:
    """Split TRAIL / TRAIL LIMIT orders into module-managed (TS_) and manual."""
    module_orders: list[dict] = []
    manual_orders: list[dict] = []
    for order in open_orders:
        if order.get("order_type") not in _TRAIL_ORDER_TYPES:
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
    """Fetch open orders from IB, including trail-specific fields."""
    await fetch_with_timeout(ib.reqAllOpenOrdersAsync(), timeout=5, default=[])
    trades = ib.openTrades()
    result = []
    for trade in trades:
        c = trade.contract
        o = trade.order
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
                "trailing_percent": getattr(o, "trailingPercent", None),
                "aux_price": getattr(o, "auxPrice", None),
                "trail_stop_price": getattr(o, "trailStopPrice", None),
            }
        )
    return result


def _parse_existing_trails(
    open_orders: list[dict],
) -> dict[tuple[str, str], dict]:
    """Extract TS_ TRAIL order details keyed by (account, position key).

    Returns {(account, key): {"trailing_percent", "aux_price", "trail_stop_price", "order_id"}}.
    First occurrence wins on duplicates; dupes should be resolved manually.
    """
    trails: dict[tuple[str, str], dict] = {}
    for order in open_orders:
        ref = order.get("order_ref", "")
        if not ref.startswith(_TS_PREFIX):
            continue
        if order.get("order_type") not in _TRAIL_ORDER_TYPES:
            continue
        key = ref[len(_TS_PREFIX) :]
        account = order.get("account", "") or ""
        composite = (account, key)
        if composite not in trails:
            trails[composite] = {
                "trailing_percent": order.get("trailing_percent"),
                "aux_price": order.get("aux_price"),
                "trail_stop_price": order.get("trail_stop_price"),
                "order_id": order.get("order_id"),
            }
    return trails


async def _cancel_orphan_orders(ib, orphan_orders: list[dict]) -> list[dict]:
    """Cancel all orphan TS_ TRAIL orders in IB."""
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


async def _place_simple_trail_order(
    ib,
    contract,
    position: dict,
    qty: int,
    trail_pct: float | None,
    trail_amt: float | None,
    trail_stop_price: float,
    order_ref: str,
) -> dict:
    """Place a TRAIL order for a naked LEAPS or stock position.

    The contract must be pre-qualified by the caller. We deliberately do not
    re-qualify here: an overwrite cancels the existing protective trail before
    placing the replacement, so the only qualification gate must run upstream
    — failing here would leave the position exposed.
    """
    from ib_async import Order

    order = Order()
    order.action = "SELL"
    order.orderType = "TRAIL"
    order.totalQuantity = qty
    # IB uses trailingPercent for % trail, auxPrice for $ trail amount. Setting
    # both is an error; the CLI guarantees exactly one is non-None.
    if trail_pct is not None:
        order.trailingPercent = trail_pct
    elif trail_amt is not None:
        order.auxPrice = trail_amt
    # trailStopPrice sets the initial trigger explicitly. Without this, IB
    # computes from the live last price at submit time — which loses the
    # max(current, avg_cost) profit-lock-in baked into our reference.
    order.trailStopPrice = trail_stop_price
    order.tif = "GTC"
    order.orderRef = order_ref
    # Pin to position's account so IB routes execution to the holding account
    # (multi-account connections default to a single account otherwise).
    if position.get("account"):
        order.account = position["account"]

    trade = ib.placeOrder(contract, order)
    return {"ok": True, "order_id": trade.order.orderId, "order_ref": order_ref}


async def _execute_position_trail(
    ib,
    analysis: dict,
    leaps_contract,
    stock_contract,
    open_orders: list[dict] | None = None,
) -> dict:
    """Place the trailing stop order for one position based on analysis.

    Caller must provide a pre-qualified IB Contract for the position type so
    qualification can never fail after cancellation. On overwrite, cancels the
    existing TS_ order before placing the replacement.
    """
    ptype = analysis["type"]
    symbol = analysis["symbol"]
    qty = analysis["qty"]
    trail = analysis["trail_stop"]
    action = trail["action"]

    if action not in ("place_new", "overwrite"):
        return {"symbol": symbol, "skipped": True, "reason": action}

    # Resolve the qualified contract BEFORE touching any open orders. A missing
    # contract means upstream qualification failed; cancelling a protective
    # trail and then failing to place the replacement would leave the position
    # exposed, so the qualification gate must run before cancellation.
    if ptype == "leaps":
        if leaps_contract is None:
            return {"symbol": symbol, "ok": False, "error": "no qualified LEAPS contract"}
        contract = leaps_contract
    else:
        if stock_contract is None:
            return {"symbol": symbol, "ok": False, "error": "no qualified stock contract"}
        contract = stock_contract

    order_ref = f"{_TS_PREFIX}{_ts_key(analysis)}"
    position_account = analysis.get("account") or ""

    # Only overwrite cancels existing TS_ orders, and only TRAIL/TRAIL LIMIT
    # ones — the rest of the module treats non-TRAIL TS_ refs as unmanaged.
    if action == "overwrite" and open_orders:
        trades_by_id = {t.order.orderId: t for t in ib.openTrades()}
        for o in open_orders:
            if o.get("order_ref") != order_ref:
                continue
            if (o.get("account") or "") != position_account:
                continue
            if o.get("order_type") not in _TRAIL_ORDER_TYPES:
                continue
            oid = o.get("order_id")
            if oid and oid in trades_by_id:
                ib.cancelOrder(trades_by_id[oid].order)

    return await _place_simple_trail_order(
        ib=ib,
        contract=contract,
        position=analysis,
        qty=qty,
        trail_pct=trail["trail_pct"],
        trail_amt=trail["trail_amt"],
        trail_stop_price=trail["initial_stop_price"],
        order_ref=order_ref,
    )


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================


async def get_trailing_stop_data(
    port: int = 7496,
    account: str | None = None,
    symbols: list[str] | None = None,
    trail_pct: float | None = 20.0,
    trail_amt: float | None = None,
    price_mode: str = "mid",
    dry_run: bool = True,
    forced: bool = False,
) -> dict:
    """Analyze stocks + naked LEAPS and manage IB TRAIL orders.

    dry_run=True (default): analyze and report; no orders placed.
    dry_run=False (--execute): cancel orphan TS_ orders, place TS_ TRAIL orders.
    forced=True: cancel and replace existing TS_ orders with current parameters
        (otherwise existing trails are preserved so IB's tracked high isn't reset).
    """
    if trail_pct is not None and trail_amt is not None:
        return {
            "generated_at": generated_at_str(),
            "data_delay": "unknown",
            "error": "Specify exactly one of trail_pct or trail_amt, not both",
        }
    if trail_pct is None and trail_amt is None:
        return {
            "generated_at": generated_at_str(),
            "data_delay": "unknown",
            "error": "Must specify trail_pct or trail_amt",
        }

    try:
        async with ib_connection(port, CLIENT_IDS.get("trailing_stop", 15), readonly=dry_run) as ib:
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
            unfiltered_positions = identify_trailable_positions(normalized)
            if symbols:
                sym_set = {s.upper() for s in symbols}
                all_positions = [p for p in unfiltered_positions if p["symbol"].upper() in sym_set]
            else:
                all_positions = unfiltered_positions

            # --- Open orders ---
            await asyncio.sleep(1)
            open_orders = await _fetch_open_orders(ib)
            all_trail_orders = summarize_all_trail_orders(open_orders)
            account_scoped_orders = filter_orders_by_account(open_orders, accounts)
            orphan_orders = detect_orphan_trail_orders(account_scoped_orders, unfiltered_positions)
            existing_trails = _parse_existing_trails(account_scoped_orders)

            cancel_results = []
            if not dry_run and orphan_orders:
                cancel_results = await _cancel_orphan_orders(ib, orphan_orders)

            if not all_positions:
                empty_output = {
                    "generated_at": generated_at_str(),
                    "data_delay": "real-time",
                    "dry_run": dry_run,
                    "forced": forced,
                    "trail_pct": trail_pct,
                    "trail_amt": trail_amt,
                    "accounts": accounts,
                    "symbols_filter": [s.upper() for s in symbols] if symbols else None,
                    "all_trail_orders": all_trail_orders,
                    "orphan_orders": orphan_orders,
                    "positions": [],
                    "message": "No trailable positions found (stocks + naked LEAPS only)",
                }
                if not dry_run:
                    empty_output["cancel_results"] = cancel_results
                return empty_output

            # --- Market data ---
            unique_symbols = list({p["symbol"] for p in all_positions})
            live = is_trading_now()

            option_positions = [p for p in all_positions if p["type"] == "leaps"]

            from trading_skills.broker.pmcc_advisor import _fetch_single_option_quote

            leaps_quote_tasks = [
                _fetch_single_option_quote(
                    ib,
                    pos["symbol"],
                    pos["leaps"]["strike"],
                    pos["leaps"]["expiry"],
                    pos["leaps"]["right"],
                )
                for pos in option_positions
            ]

            if live:
                spot_task = fetch_spot_prices(ib, unique_symbols)
            else:
                from trading_skills.broker.pmcc_advisor import _fetch_yf_spot_prices

                spot_task = _fetch_yf_spot_prices(unique_symbols)

            results = await asyncio.gather(spot_task, *leaps_quote_tasks)
            spot_prices: dict[str, float] = results[0]
            leaps_quotes = list(results[1 : 1 + len(option_positions)])

            data_delay = "real-time" if live else "stalled - using last price"
            for q in leaps_quotes:
                if q and q.get("stale"):
                    data_delay = "stalled - using last price"
                    break

            leaps_quote_map: dict[int, dict] = {
                id(pos): leaps_quotes[i] or {} for i, pos in enumerate(option_positions)
            }

            # --- Qualify contracts (execute mode) ---
            # Store the full qualified Contract objects (not just conIds) so
            # _execute_position_trail can hand them straight to placeOrder
            # without a second qualification call — re-qualifying at order time
            # could fail after the existing protective trail was cancelled.
            qualified_stock_contracts: dict[str, object] = {}
            qualified_leaps_contracts: dict[int, object] = {}
            if not dry_run:
                from ib_async import Option as IBOption
                from ib_async import Stock

                stock_syms = list({p["symbol"] for p in all_positions if p["type"] == "stock"})
                if stock_syms:
                    stock_contracts = [Stock(sym, "SMART", "USD") for sym in stock_syms]
                    qs = await fetch_with_timeout(
                        ib.qualifyContractsAsync(*stock_contracts), timeout=15, default=[]
                    )
                    qualified_stock_contracts = {qc.symbol: qc for qc in qs if qc is not None}

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
                        qualified_leaps_contracts[id(pos)] = ql[0]

            # --- Per-position analysis ---
            analyzed_positions = []
            order_results = []

            for pos in all_positions:
                sym = pos["symbol"]
                ptype = pos["type"]
                spot = spot_prices.get(sym)
                if not spot:
                    continue

                if ptype == "leaps":
                    lq = leaps_quote_map.get(id(pos), {})
                    current_price = get_option_price(lq, price_mode)
                else:
                    current_price = spot

                existing_trail = existing_trails.get((pos.get("account", "") or "", _ts_key(pos)))

                analysis = build_trail_analysis(
                    position=pos,
                    underlying_price=spot,
                    current_price=current_price,
                    existing_trail=existing_trail,
                    trail_pct=trail_pct,
                    trail_amt=trail_amt,
                    forced=forced,
                )
                analyzed_positions.append(analysis)

                if not dry_run:
                    res = await _execute_position_trail(
                        ib=ib,
                        analysis=analysis,
                        leaps_contract=qualified_leaps_contracts.get(id(pos)),
                        stock_contract=qualified_stock_contracts.get(sym),
                        open_orders=open_orders,
                    )
                    order_results.append(res)

            if not dry_run and order_results:
                await asyncio.sleep(3)

            output = {
                "generated_at": generated_at_str(),
                "data_delay": data_delay,
                "dry_run": dry_run,
                "forced": forced,
                "trail_pct": trail_pct,
                "trail_amt": trail_amt,
                "accounts": accounts,
                "symbols_filter": [s.upper() for s in symbols] if symbols else None,
                "all_trail_orders": all_trail_orders,
                "orphan_orders": orphan_orders,
                "positions": analyzed_positions,
            }
            if not dry_run:
                output["cancel_results"] = cancel_results
                output["order_results"] = order_results
            return output

    except ConnectionError as e:
        return {
            "generated_at": generated_at_str(),
            "data_delay": "unknown",
            "error": f"{e}. Is TWS/Gateway running?",
        }

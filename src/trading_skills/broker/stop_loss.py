# ABOUTME: Stop-loss management for PMCC (diagonal spread) positions in IB portfolio.
# ABOUTME: Delta-neutral watermarks, LEAPS stop prices, alerts, and orphan order detection.

import asyncio

from scipy.optimize import brentq

from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_positions,
    fetch_spot_prices,
    ib_connection,
    normalize_positions,
)
from trading_skills.broker.pmcc_advisor import (
    _identify_pmcc_spreads,
    calc_delta,
    calc_iv,
    filter_spreads_by_symbols,
    get_option_price,
)
from trading_skills.utils import (
    days_to_expiry,
    fetch_with_timeout,
    generated_at_str,
    is_trading_now,
)

RISK_FREE_RATE = 0.045

# OrderRef prefix for stop-loss orders placed by this module
_SL_PREFIX = "SL_"


# ===========================================================================
# ANALYTICS (no IBKR dependency — fully testable in isolation)
# ===========================================================================


def find_delta_neutral_spot(
    long_strike: float,
    long_dte: float,
    long_iv: float,
    short_strike: float,
    short_dte: float,
    short_iv: float,
    spot_hint: float,
) -> float | None:
    """Find spot price where long_delta == short_delta (net delta = 0, max spread value).

    For a PMCC (long LEAPS + short near-term call), net delta is positive at typical
    spot levels and crosses zero as the spot rises past the short strike.  The crossing
    point is the delta-neutral watermark: beyond it the short leg's gamma dominates
    and the spread starts losing value.
    """

    def net_delta(s: float) -> float:
        ld = calc_delta(s, long_strike, max(long_dte, 1 / 24), long_iv, "C")
        sd = calc_delta(s, short_strike, max(short_dte, 1 / 24), short_iv, "C")
        return ld - sd

    lo = spot_hint * 0.8
    hi = spot_hint * 5.0

    f_lo = net_delta(lo)
    f_hi = net_delta(hi)

    if f_lo * f_hi >= 0:
        return None

    try:
        return round(brentq(net_delta, lo, hi, xtol=0.01), 2)
    except ValueError:
        return None


def calc_leaps_stop_basis(
    leaps_market_price: float | None,
    leaps_avg_cost: float,
) -> float:
    """Reference basis for LEAPS stop loss: max(market_price, cost_basis).

    Uses cost_basis as floor so the stop level never ratchets down.
    """
    if leaps_market_price and leaps_market_price > 0:
        return max(leaps_market_price, leaps_avg_cost)
    return leaps_avg_cost


def calc_leaps_stop_price(
    leaps_market_price: float | None,
    leaps_avg_cost: float,
    stop_pct: float,
) -> float:
    """Price at which to exit the spread due to LEAPS loss."""
    basis = calc_leaps_stop_basis(leaps_market_price, leaps_avg_cost)
    return round(basis * (1.0 - stop_pct / 100.0), 2)


def calc_short_premium_decay_pct(
    premium_received: float,
    current_price: float,
) -> float:
    """Percentage of short premium already captured (0 = intact, 100 = fully decayed)."""
    if premium_received <= 0:
        return 0.0
    captured = premium_received - current_price
    return (captured / premium_received) * 100.0


def check_alerts(
    short_premium_received: float,
    short_current_price: float | None,
    short_strike: float,
    spot: float,
    leaps_current_price: float | None,
    leaps_avg_cost: float,
    stop_pct: float,
    short_near_strike_pct: float = 5.0,
) -> list[dict]:
    """Compute informational alerts for a spread position.

    Returns a list of alert dicts, each with at minimum 'type' and 'message' keys.
    Does not return exit actions — alerts only.
    """
    alerts = []

    # Short premium ≥ 90% decayed
    if short_current_price is not None and short_premium_received > 0:
        decay_pct = calc_short_premium_decay_pct(short_premium_received, short_current_price)
        if decay_pct >= 90.0:
            alerts.append(
                {
                    "type": "short_premium_decay",
                    "message": f"Short premium {decay_pct:.1f}% captured — close or roll",
                    "decay_pct": round(decay_pct, 1),
                    "threshold_pct": 90.0,
                }
            )

    # Spot within X% below (or above) the short strike — assignment risk zone
    if short_strike > 0:
        gap_pct = (short_strike - spot) / short_strike * 100.0
        if gap_pct <= short_near_strike_pct:
            direction = "above" if spot >= short_strike else "below"
            alerts.append(
                {
                    "type": "short_near_strike",
                    "message": (
                        f"Spot ${spot:.2f} is {abs(gap_pct):.1f}% {direction} "
                        f"short strike ${short_strike:.2f} (threshold {short_near_strike_pct:.0f}%)"
                    ),
                    "gap_pct": round(gap_pct, 1),
                    "threshold_pct": short_near_strike_pct,
                }
            )

    # LEAPS early warning at stop_pct / 2
    if leaps_current_price is not None:
        early_warning_pct = stop_pct / 2.0
        basis = calc_leaps_stop_basis(leaps_current_price, leaps_avg_cost)
        loss_pct = (1.0 - leaps_current_price / basis) * 100.0
        if loss_pct >= early_warning_pct:
            alerts.append(
                {
                    "type": "leaps_early_warning",
                    "message": (
                        f"LEAPS down {loss_pct:.1f}% from basis ${basis:.2f} "
                        f"(stop fires at {stop_pct:.0f}%, warning at {early_warning_pct:.0f}%)"
                    ),
                    "current_loss_pct": round(loss_pct, 1),
                    "threshold_pct": early_warning_pct,
                    "basis": round(basis, 2),
                }
            )

    return alerts


def detect_orphan_orders(
    open_orders: list[dict],
    active_spreads: list[dict],
) -> list[dict]:
    """Find stop-loss orders (SL_ prefix) for spreads no longer in the portfolio."""
    active_keys: set[str] = set()
    for spread in active_spreads:
        sym = spread["symbol"]
        short = spread["short"]
        long_ = spread["long"]
        active_keys.add(f"{sym}_{short['strike']}_{short['expiry']}")
        active_keys.add(f"{sym}_{long_['strike']}_{long_['expiry']}")

    orphans = []
    for order in open_orders:
        ref = order.get("order_ref", "")
        if not ref.startswith(_SL_PREFIX):
            continue
        # Ref format: SL_<TYPE>_<SYM>_<STRIKE>_<EXPIRY>
        parts = ref.split("_")
        if len(parts) >= 5:
            sym = parts[2]
            strike = parts[3]
            expiry = parts[4]
            key = f"{sym}_{strike}_{expiry}"
            if key not in active_keys:
                orphans.append(order)

    return orphans


def _sl_order_ref(direction: str, symbol: str, strike: float, expiry: str) -> str:
    """Build consistent orderRef string for a stop-loss order leg."""
    return f"{_SL_PREFIX}{direction}_{symbol}_{strike}_{expiry}"


def _watermark_action(
    new_watermark: float | None,
    existing_watermark: float | None,
    forced: bool,
) -> str:
    """Decide what action to take for an existing vs new watermark.

    Returns: 'place_new' | 'preserve_existing' | 'overwrite' | 'no_watermark'
    """
    if new_watermark is None:
        return "no_watermark"
    if existing_watermark is None:
        return "place_new"
    if existing_watermark >= new_watermark:
        return "overwrite" if forced else "preserve_existing"
    return "place_new"


def build_stop_analysis(
    symbol: str,
    account: str,
    qty: int,
    spot: float,
    long_pos: dict,
    short_pos: dict,
    long_price: float | None,
    short_price: float | None,
    long_iv: float | None,
    short_iv: float | None,
    long_dte: float,
    short_dte: float,
    existing_rise_watermark: float | None,
    existing_fall_stop: float | None,
    stop_pct: float,
    short_near_strike_pct: float,
    forced: bool,
) -> dict:
    """Compute the full stop-loss analysis for one PMCC spread."""

    # --- Rising spot: delta-neutral watermark ---
    watermark_spot = None
    if long_iv and short_iv:
        watermark_spot = find_delta_neutral_spot(
            long_strike=long_pos["strike"],
            long_dte=long_dte,
            long_iv=long_iv,
            short_strike=short_pos["strike"],
            short_dte=short_dte,
            short_iv=short_iv,
            spot_hint=spot,
        )

    rise_action = _watermark_action(watermark_spot, existing_rise_watermark, forced)

    # --- Falling spot: LEAPS stop ---
    leaps_stop_price = calc_leaps_stop_price(long_price, long_pos["avg_cost"], stop_pct)
    leaps_stop_basis = calc_leaps_stop_basis(long_price, long_pos["avg_cost"])
    leaps_loss_pct = round((1.0 - long_price / leaps_stop_basis) * 100.0, 1) if long_price else None

    fall_action = _watermark_action(leaps_stop_price, existing_fall_stop, forced)

    # --- Alerts ---
    alerts = check_alerts(
        short_premium_received=abs(short_pos["avg_cost"]),
        short_current_price=short_price,
        short_strike=short_pos["strike"],
        spot=spot,
        leaps_current_price=long_price,
        leaps_avg_cost=long_pos["avg_cost"],
        stop_pct=stop_pct,
        short_near_strike_pct=short_near_strike_pct,
    )

    short_decay_pct = None
    if short_price is not None:
        short_decay_pct = round(
            calc_short_premium_decay_pct(abs(short_pos["avg_cost"]), short_price), 1
        )

    return {
        "symbol": symbol,
        "account": account,
        "qty": qty,
        "underlying_price": round(spot, 2),
        "long": {
            "strike": long_pos["strike"],
            "expiry": long_pos["expiry"],
            "dte": long_dte,
            "avg_cost": long_pos["avg_cost"],
            "current_price": round(long_price, 2) if long_price else None,
            "stop_basis": round(leaps_stop_basis, 2),
            "stop_price": leaps_stop_price,
            "loss_pct_current": leaps_loss_pct,
        },
        "short": {
            "strike": short_pos["strike"],
            "expiry": short_pos["expiry"],
            "dte": short_dte,
            "premium_received": abs(short_pos["avg_cost"]),
            "current_price": round(short_price, 2) if short_price else None,
            "decay_pct": short_decay_pct,
        },
        "rising_watermark": {
            "spot": watermark_spot,
            "action": rise_action,
            "existing_watermark": existing_rise_watermark,
        },
        "falling_stop": {
            "leaps_stop_price": leaps_stop_price,
            "leaps_current_price": round(long_price, 2) if long_price else None,
            "action": fall_action,
            "existing_stop_price": existing_fall_stop,
        },
        "alerts": alerts,
    }


# ===========================================================================
# IBKR DATA LAYER
# ===========================================================================


async def _fetch_open_orders(ib) -> list[dict]:
    """Fetch all open orders from IB, normalized to plain dicts."""

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


def _parse_existing_watermarks(open_orders: list[dict]) -> dict[str, dict]:
    """Extract watermark prices from existing SL orders keyed by leg key.

    Returns {leg_key: {'rise': float|None, 'fall': float|None}}.
    leg_key format: SYMBOL_STRIKE_EXPIRY
    """
    watermarks: dict[str, dict] = {}
    for order in open_orders:
        ref = order.get("order_ref", "")
        if not ref.startswith(_SL_PREFIX):
            continue
        parts = ref.split("_")
        if len(parts) < 5:
            continue
        direction = parts[1]  # RISE or FALL
        sym = parts[2]
        strike = parts[3]
        expiry = parts[4]
        key = f"{sym}_{strike}_{expiry}"

        conditions = order.get("conditions", [])
        cond_price = conditions[0]["price"] if conditions else None

        if key not in watermarks:
            watermarks[key] = {"rise": None, "fall": None}

        if direction == "RISE" and cond_price is not None:
            existing = watermarks[key]["rise"]
            watermarks[key]["rise"] = (
                max(existing, cond_price) if existing is not None else cond_price
            )
        elif direction == "FALL" and cond_price is not None:
            existing = watermarks[key]["fall"]
            watermarks[key]["fall"] = (
                min(existing, cond_price) if existing is not None else cond_price
            )

    return watermarks


async def _place_conditional_order(
    ib,
    symbol: str,
    strike: float,
    expiry: str,
    right: str,
    action: str,
    qty: int,
    condition_con_id: int,
    condition_price: float,
    is_more: bool,
    order_ref: str,
) -> dict:
    """Submit one leg of a conditional stop-loss order to IB."""
    from ib_async import Option, Order, PriceCondition

    contract = Option(symbol, expiry, strike, right, "SMART", currency="USD")
    qualified = await fetch_with_timeout(ib.qualifyContractsAsync(contract), timeout=10, default=[])
    if not qualified:
        return {"ok": False, "error": f"Could not qualify {symbol} {strike} {expiry}"}

    condition = PriceCondition()
    condition.conId = condition_con_id
    condition.exch = "SMART"
    condition.isMore = is_more
    condition.price = condition_price

    order = Order()
    order.action = action
    order.orderType = "MKT"
    order.totalQuantity = qty
    order.conditions = [condition]
    order.conditionsIgnoreRth = True
    order.orderRef = order_ref
    order.tif = "GTC"

    trade = ib.placeOrder(qualified[0], order)
    return {"ok": True, "order_id": trade.order.orderId, "order_ref": order_ref}


async def _execute_stop_orders(
    ib,
    analysis: dict,
    stock_con_id: int,
    price_mode: str,
    forced: bool,
) -> list[dict]:
    """Place or skip stop-loss orders for one spread based on analysis."""
    results = []
    symbol = analysis["symbol"]
    qty = analysis["qty"]
    long_info = analysis["long"]
    short_info = analysis["short"]

    # Rising watermark: both legs close when underlying hits watermark_spot
    rise = analysis["rising_watermark"]
    if rise["action"] in ("place_new", "overwrite"):
        watermark_spot = rise["spot"]
        for action, strike, expiry, ref_direction in [
            ("BUY", short_info["strike"], short_info["expiry"], "RISE"),
            ("SELL", long_info["strike"], long_info["expiry"], "RISE"),
        ]:
            ref = _sl_order_ref(ref_direction, symbol, strike, expiry)
            res = await _place_conditional_order(
                ib=ib,
                symbol=symbol,
                strike=strike,
                expiry=expiry,
                right="C",
                action=action,
                qty=qty,
                condition_con_id=stock_con_id,
                condition_price=watermark_spot,
                is_more=True,
                order_ref=ref,
            )
            results.append({"leg": f"{action} {strike} {expiry}", **res})

    # Falling stop: both legs close when LEAPS price drops to stop_price
    fall = analysis["falling_stop"]
    if fall["action"] in ("place_new", "overwrite"):
        leaps_stop_price = fall["leaps_stop_price"]
        # Need LEAPS contract conId for the condition
        from ib_async import Option

        leaps_contract = Option(
            symbol, long_info["expiry"], long_info["strike"], "C", "SMART", currency="USD"
        )
        qualified_leaps = await fetch_with_timeout(
            ib.qualifyContractsAsync(leaps_contract), timeout=10, default=[]
        )
        leaps_con_id = qualified_leaps[0].conId if qualified_leaps else stock_con_id

        for action, strike, expiry, ref_direction in [
            ("SELL", long_info["strike"], long_info["expiry"], "FALL"),
            ("BUY", short_info["strike"], short_info["expiry"], "FALL"),
        ]:
            ref = _sl_order_ref(ref_direction, symbol, strike, expiry)
            res = await _place_conditional_order(
                ib=ib,
                symbol=symbol,
                strike=strike,
                expiry=expiry,
                right="C",
                action=action,
                qty=qty,
                condition_con_id=leaps_con_id,
                condition_price=leaps_stop_price,
                is_more=False,
                order_ref=ref,
            )
            results.append({"leg": f"{action} {strike} {expiry}", **res})

    return results


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================


async def get_stop_loss_data(
    port: int = 7496,
    account: str | None = None,
    symbols: list[str] | None = None,
    stop_pct: float = 50.0,
    short_near_strike_pct: float = 5.0,
    price_mode: str = "mid",
    dry_run: bool = True,
    forced: bool = False,
) -> dict:
    """Analyze PMCC positions and manage stop-loss conditional orders.

    dry_run=True (default): compute and report; do not submit any orders.
    dry_run=False: submit conditional orders to IB.
    forced=True: overwrite existing watermarks even if the new one is lower.
    """
    try:
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

            # --- Positions and spreads ---
            raw = await fetch_positions(ib, account=account)
            normalized = normalize_positions(raw)
            spreads = _identify_pmcc_spreads(normalized)
            spreads = filter_spreads_by_symbols(spreads, symbols)

            # --- Open orders (for orphan detection + existing watermarks) ---
            await asyncio.sleep(1)
            open_orders = await _fetch_open_orders(ib)
            orphan_orders = detect_orphan_orders(open_orders, spreads)
            existing_watermarks = _parse_existing_watermarks(open_orders)

            if not spreads:
                return {
                    "generated_at": generated_at_str(),
                    "data_delay": "real-time",
                    "dry_run": dry_run,
                    "forced": forced,
                    "accounts": accounts,
                    "orphan_orders": orphan_orders,
                    "stop_actions": [],
                    "message": "No PMCC (diagonal call spread) positions found",
                }

            unique_symbols = list({s["symbol"] for s in spreads})
            n = len(spreads)
            live = is_trading_now()

            # --- Fetch spot + option quotes ---
            if live:
                from trading_skills.broker.pmcc_advisor import _fetch_single_option_quote

                phase1 = await asyncio.gather(
                    fetch_spot_prices(ib, unique_symbols),
                    *[
                        _fetch_single_option_quote(
                            ib, s["symbol"], s["short"]["strike"], s["short"]["expiry"], "C"
                        )
                        for s in spreads
                    ],
                    *[
                        _fetch_single_option_quote(
                            ib, s["symbol"], s["long"]["strike"], s["long"]["expiry"], "C"
                        )
                        for s in spreads
                    ],
                )
            else:
                from trading_skills.broker.pmcc_advisor import (
                    _fetch_yf_option_quote,
                    _fetch_yf_spot_prices,
                )

                phase1 = await asyncio.gather(
                    _fetch_yf_spot_prices(unique_symbols),
                    *[
                        _fetch_yf_option_quote(
                            s["symbol"], s["short"]["expiry"], s["short"]["strike"], "C"
                        )
                        for s in spreads
                    ],
                    *[
                        _fetch_yf_option_quote(
                            s["symbol"], s["long"]["expiry"], s["long"]["strike"], "C"
                        )
                        for s in spreads
                    ],
                )

            spot_prices: dict[str, float] = phase1[0]
            short_quotes: list = list(phase1[1 : n + 1])
            long_quotes: list = list(phase1[n + 1 : 2 * n + 1])
            data_delay = "real-time" if live else "stalled - using last price"

            # --- Stock conIds for conditional orders (only needed for EXECUTE) ---
            stock_con_ids: dict[str, int] = {}
            if not dry_run:
                from ib_async import Stock

                stock_contracts = [Stock(sym, "SMART", "USD") for sym in unique_symbols]
                qualified_stocks = await fetch_with_timeout(
                    ib.qualifyContractsAsync(*stock_contracts), timeout=15, default=[]
                )
                stock_con_ids = {qc.symbol: qc.conId for qc in qualified_stocks}

            # --- Per-spread analysis ---
            stop_actions = []
            order_results: dict[str, list] = {}

            for i, spread in enumerate(spreads):
                symbol = spread["symbol"]
                long_pos = spread["long"]
                short_pos = spread["short"]
                qty = spread["qty"]
                spot = spot_prices.get(symbol)
                if not spot:
                    continue

                short_quote = short_quotes[i] or {}
                long_quote = long_quotes[i] or {}

                if short_quote.get("stale") or long_quote.get("stale"):
                    data_delay = "stalled - using last price"

                long_dte = days_to_expiry(long_pos["expiry"])
                short_dte = days_to_expiry(short_pos["expiry"])

                short_price = get_option_price(short_quote, price_mode)
                long_price = get_option_price(long_quote, price_mode)

                short_iv = (
                    (
                        calc_iv(short_price, spot, short_pos["strike"], short_dte, "C")
                        if short_price
                        else None
                    )
                    or (short_quote.get("ib_iv_pct", 0) or 0) / 100
                    or None
                )
                long_iv = (
                    (
                        calc_iv(long_price, spot, long_pos["strike"], long_dte, "C")
                        if long_price
                        else None
                    )
                    or (long_quote.get("ib_iv_pct", 0) or 0) / 100
                    or None
                )

                short_key = f"{symbol}_{short_pos['strike']}_{short_pos['expiry']}"
                long_key = f"{symbol}_{long_pos['strike']}_{long_pos['expiry']}"
                spread_wm = existing_watermarks.get(short_key, {})
                existing_rise = spread_wm.get("rise")
                existing_fall = existing_watermarks.get(long_key, {}).get("fall")

                analysis = build_stop_analysis(
                    symbol=symbol,
                    account=account or accounts[0],
                    qty=qty,
                    spot=spot,
                    long_pos=long_pos,
                    short_pos=short_pos,
                    long_price=long_price,
                    short_price=short_price,
                    long_iv=long_iv,
                    short_iv=short_iv,
                    long_dte=long_dte,
                    short_dte=short_dte,
                    existing_rise_watermark=existing_rise,
                    existing_fall_stop=existing_fall,
                    stop_pct=stop_pct,
                    short_near_strike_pct=short_near_strike_pct,
                    forced=forced,
                )
                stop_actions.append(analysis)

                if not dry_run:
                    stock_con_id = stock_con_ids.get(symbol)
                    if stock_con_id:
                        results = await _execute_stop_orders(
                            ib=ib,
                            analysis=analysis,
                            stock_con_id=stock_con_id,
                            price_mode=price_mode,
                            forced=forced,
                        )
                        order_results[symbol] = results

            output = {
                "generated_at": generated_at_str(),
                "data_delay": data_delay,
                "dry_run": dry_run,
                "forced": forced,
                "stop_pct": stop_pct,
                "short_near_strike_pct": short_near_strike_pct,
                "accounts": accounts,
                "symbols_filter": [s.upper() for s in symbols] if symbols else None,
                "orphan_orders": orphan_orders,
                "stop_actions": stop_actions,
            }
            if not dry_run:
                output["order_results"] = order_results
            return output

    except ConnectionError as e:
        return {
            "generated_at": generated_at_str(),
            "data_delay": "unknown",
            "error": f"{e}. Is TWS/Gateway running?",
        }

# ABOUTME: Operational PMCC bot — scans for new diagonal-call opportunities, opens them as
# ABOUTME: combo orders, and actively manages the short leg (close at decay threshold + reroll).
# ABOUTME: Options only (long leg is ALWAYS a long call, never a future). Dry-run by default.

import asyncio

from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_positions,
    ib_connection,
    normalize_positions,
)
from trading_skills.broker.pmcc_advisor import (
    _fetch_single_option_quote,
    _identify_pmcc_spreads,
    get_option_price,
)
from trading_skills.scanner_pmcc import analyze_pmcc
from trading_skills.utils import days_to_expiry, generated_at_str, is_trading_now

# Order tagging — the bot manages ONLY orders/positions it created. The user's manual
# positions (e.g. NQ futures + JNJ stock) are never equity diagonal-call spreads, so the
# exit-management detector excludes them by construction.
ENTRY_REF_PREFIX = "BOT_PMCC"
CLOSE_REF_PREFIX = "BOT_CLOSE"

# Defaults (operational policy agreed with the user)
DEFAULT_TOP_N = 3
DEFAULT_DECAY_THRESHOLD = 0.70  # close short once 70% of premium has decayed
DEFAULT_MIN_SCORE = 0.0


# ===========================================================================
# PURE / TESTABLE LOGIC (no IBKR dependency)
# ===========================================================================


def _ibkr_expiry(yf_expiry: str) -> str:
    """Convert a scanner expiry 'YYYY-MM-DD' to IBKR 'YYYYMMDD'."""
    return yf_expiry.replace("-", "")


def entry_cost_usd(candidate: dict) -> float:
    """Cash outlay to open the diagonal = net debit per share x 100 (one contract).

    net_debit = leaps_mid - short_mid. This is what leaves the account on entry and
    the figure we gate against available margin/funds.
    """
    net_debit = candidate.get("metrics", {}).get("net_debit", 0) or 0
    return round(net_debit * 100, 2)


def order_ref_for(symbol: str, short_expiry: str) -> str:
    """Stable orderRef tag identifying a bot-opened diagonal by symbol + short expiry."""
    return f"{ENTRY_REF_PREFIX}_{symbol.upper()}_{_ibkr_expiry(short_expiry)}"


def select_entries(
    candidates: list[dict],
    available_funds: float,
    top_n: int = DEFAULT_TOP_N,
    min_score: float = DEFAULT_MIN_SCORE,
    exclude_symbols: set | None = None,
) -> tuple[list[dict], list[dict]]:
    """Pick up to ``top_n`` candidates that fit within ``available_funds``.

    Sorted by PMCC score then annual yield (matching the scanner ranking). A candidate is
    opened only if the running committed capital plus its entry cost stays within
    ``available_funds``; otherwise it is skipped with an explicit reason. Symbols in
    ``exclude_symbols`` (already held or with a pending bot order) are never re-opened.
    Returns ``(selected, skipped)`` where each entry carries an ``entry_cost`` field and
    skips carry a ``skip_reason``.
    """
    exclude = {s.upper() for s in (exclude_symbols or set())}
    skipped: list[dict] = []
    eligible: list[dict] = []
    for c in candidates:
        if "metrics" not in c or c.get("pmcc_score", -99) < min_score:
            continue
        if c["symbol"].upper() in exclude:
            skipped.append({**c, "skip_reason": "already holding/pending — not re-opened"})
            continue
        eligible.append(c)
    eligible.sort(
        key=lambda c: (
            c.get("pmcc_score", 0),
            c.get("metrics", {}).get("annual_yield_est_pct", 0),
        ),
        reverse=True,
    )

    selected: list[dict] = []
    committed = 0.0

    for c in eligible:
        cost = entry_cost_usd(c)
        if len(selected) >= top_n:
            skipped.append({**c, "skip_reason": f"beyond top-{top_n}"})
            continue
        if committed + cost > available_funds:
            skipped.append(
                {
                    **c,
                    "entry_cost": cost,
                    "skip_reason": (
                        f"insufficient funds: needs ${cost:,.0f}, "
                        f"${available_funds - committed:,.0f} headroom left"
                    ),
                }
            )
            continue
        committed += cost
        selected.append({**c, "entry_cost": cost})

    return selected, skipped


def short_decay_pct(premium_received: float, current_short_price: float) -> float:
    """Fraction of the short premium that has decayed.

    1.0 means the short is worthless (full profit captured); 0.0 means unchanged;
    negative means the short moved against us (now worth more than received).
    """
    if not premium_received or premium_received <= 0:
        return 0.0
    return (premium_received - current_short_price) / premium_received


def should_close_short(
    premium_received: float,
    current_short_price: float,
    threshold: float = DEFAULT_DECAY_THRESHOLD,
) -> bool:
    """True when the short has decayed at/above the threshold and is worth closing/rolling."""
    return short_decay_pct(premium_received, current_short_price) >= threshold


def build_entry_plan(candidate: dict) -> dict:
    """Build a structured entry order plan (no IBKR call) for one diagonal candidate.

    BUY the LEAPS call + SELL the short call as a single combo at the net-debit limit.
    """
    symbol = candidate["symbol"]
    leaps = candidate["leaps"]
    short = candidate["short"]
    net_debit = candidate.get("metrics", {}).get("net_debit", 0)
    return {
        "symbol": symbol,
        "action": "open_diagonal",
        "order_ref": order_ref_for(symbol, short["expiry"]),
        "limit_price": round(net_debit, 2),
        "entry_cost": entry_cost_usd(candidate),
        "score": candidate.get("pmcc_score"),
        "legs": [
            {
                "action": "BUY",
                "right": "C",
                "expiry": leaps["expiry"],
                "strike": leaps["strike"],
                "mid": leaps.get("mid"),
                "delta": leaps.get("delta"),
            },
            {
                "action": "SELL",
                "right": "C",
                "expiry": short["expiry"],
                "strike": short["strike"],
                "mid": short.get("mid"),
                "delta": short.get("delta"),
            },
        ],
    }


# ===========================================================================
# IBKR I/O
# ===========================================================================


async def _available_funds(ib, account: str) -> dict:
    """Return {available_funds, excess_liquidity, maintenance_margin, net_liquidation}."""
    summary = await ib.accountSummaryAsync(account)
    tags = {item.tag: item.value for item in summary}

    def _f(tag: str) -> float | None:
        v = tags.get(tag)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "available_funds": _f("AvailableFunds"),
        "excess_liquidity": _f("ExcessLiquidity"),
        "maintenance_margin": _f("MaintMarginReq"),
        "net_liquidation": _f("NetLiquidation"),
    }


async def _place_diagonal_combo(ib, plan: dict, account: str | None) -> tuple[dict, object | None]:
    """Place a combo BAG order: BUY LEAPS call + SELL short call, LMT at net debit.

    Returns ``(result_dict, trade)`` so the caller can wait on the trade's status.
    """
    from ib_async import ComboLeg, Contract, Option, Order

    symbol = plan["symbol"]
    leaps_leg, short_leg = plan["legs"]

    leaps_contract = Option(
        symbol, _ibkr_expiry(leaps_leg["expiry"]), leaps_leg["strike"], "C", "SMART"
    )
    short_contract = Option(
        symbol, _ibkr_expiry(short_leg["expiry"]), short_leg["strike"], "C", "SMART"
    )
    qualified = await ib.qualifyContractsAsync(leaps_contract, short_contract)
    qualified = [c for c in qualified if c is not None and getattr(c, "conId", None)]
    if len(qualified) < 2:
        return {
            "ok": False,
            "order_ref": plan["order_ref"],
            "error": f"qualify failed for {symbol}",
        }, None

    legs = []
    buy_leg = ComboLeg()
    buy_leg.conId = qualified[0].conId
    buy_leg.ratio = 1
    buy_leg.action = "BUY"
    buy_leg.exchange = "SMART"
    legs.append(buy_leg)

    sell_leg = ComboLeg()
    sell_leg.conId = qualified[1].conId
    sell_leg.ratio = 1
    sell_leg.action = "SELL"
    sell_leg.exchange = "SMART"
    legs.append(sell_leg)

    combo = Contract()
    combo.symbol = symbol
    combo.secType = "BAG"
    combo.currency = "USD"
    combo.exchange = "SMART"
    combo.comboLegs = legs

    order = Order()
    order.action = "BUY"  # paying the net debit
    order.orderType = "LMT"
    order.lmtPrice = plan["limit_price"]
    order.totalQuantity = 1
    order.orderRef = plan["order_ref"]
    order.tif = "DAY"
    if account:
        order.account = account

    trade = ib.placeOrder(combo, order)
    return {"ok": True, "order_ref": plan["order_ref"], "order_id": trade.order.orderId}, trade


async def _place_buy_to_close(
    ib, symbol: str, short: dict, qty: int, account: str | None
) -> tuple[dict, object | None]:
    """Buy back a short call to close it. LMT at the short's current mid (best-effort).

    Returns ``(result_dict, trade)`` so the caller can wait on the trade's status.
    """
    from ib_async import Option, Order

    contract = Option(symbol, _ibkr_expiry(short["expiry"]), short["strike"], "C", "SMART")
    qualified = await ib.qualifyContractsAsync(contract)
    qualified = [c for c in qualified if c is not None and getattr(c, "conId", None)]
    if not qualified:
        return {"ok": False, "error": f"qualify failed for {symbol} close"}, None

    order = Order()
    order.action = "BUY"
    order.orderType = "LMT"
    order.lmtPrice = short["limit_price"]
    order.totalQuantity = qty
    order.orderRef = f"{CLOSE_REF_PREFIX}_{symbol.upper()}_{_ibkr_expiry(short['expiry'])}"
    order.tif = "DAY"
    if account:
        order.account = account

    trade = ib.placeOrder(qualified[0], order)
    return {"ok": True, "order_ref": order.orderRef, "order_id": trade.order.orderId}, trade


# ===========================================================================
# ORCHESTRATION
# ===========================================================================


async def _pending_bot_symbols(ib) -> set:
    """Symbols that already have a working bot order (entry or close), across all clients.

    reqAllOpenOrders surfaces orders placed by other client sessions too, sidestepping the
    single-client visibility gotcha. Prevents duplicate entries on repeated autonomous runs.
    """
    try:
        trades = await ib.reqAllOpenOrdersAsync()
    except Exception:
        return set()
    pending = set()
    for t in trades:
        ref = getattr(t.order, "orderRef", "") or ""
        if ref.startswith(ENTRY_REF_PREFIX) or ref.startswith(CLOSE_REF_PREFIX):
            sym = getattr(t.contract, "symbol", "")
            if sym:
                pending.add(sym.upper())
    return pending


async def _confirm_statuses(ib, placed: list[tuple], settle: float = 5.0) -> list[dict]:
    """Wait for placed orders to reach a stable status before disconnecting, then report it.

    Orders transmit asynchronously; disconnecting while still PendingSubmit kills them. We
    sleep ``settle`` seconds, then read each trade's real status and flag rejections.
    """
    if not placed:
        return []
    await asyncio.sleep(settle)
    results = []
    for res, trade in placed:
        if trade is not None:
            status = trade.orderStatus.status
            res["status"] = status
            if status in ("Cancelled", "ApiCancelled", "Inactive"):
                res["ok"] = False
                msgs = [le.message for le in trade.log if le.message]
                res["error"] = msgs[-1] if msgs else f"order {status}"
        results.append(res)
    return results


async def _scan_candidates(symbols: list[str]) -> list[dict]:
    """Run the (synchronous, network-bound) PMCC scanner across symbols in parallel."""
    tasks = [asyncio.to_thread(analyze_pmcc, sym) for sym in symbols]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r and "pmcc_score" in r]


async def _build_exit_actions(
    ib, spreads: list[dict], decay_threshold: float, price_mode: str
) -> list[dict]:
    """For each bot-managed diagonal, decide whether the short should be closed/rolled."""
    actions = []
    for sp in spreads:
        symbol = sp["symbol"]
        short = sp["short"]
        qty = sp["qty"]
        premium_received = abs(short.get("avg_cost", 0))

        quote = await _fetch_single_option_quote(ib, symbol, short["strike"], short["expiry"], "C")
        current_price = get_option_price(quote or {}, price_mode)
        decay = short_decay_pct(premium_received, current_price or 0)
        close = current_price is not None and should_close_short(
            premium_received, current_price, decay_threshold
        )
        actions.append(
            {
                "symbol": symbol,
                "qty": qty,
                "short_strike": short["strike"],
                "short_expiry": short["expiry"],
                "short_dte": days_to_expiry(short["expiry"]),
                "premium_received": round(premium_received, 2),
                "current_short_price": round(current_price, 2) if current_price else None,
                "decay_pct": round(decay * 100, 1),
                "action": "close_and_reroll" if close else "hold",
                "limit_price": round(current_price, 2) if current_price else None,
            }
        )
    return actions


async def run_pmcc_bot(
    symbols: list[str],
    port: int = 7497,
    account: str | None = None,
    top_n: int = DEFAULT_TOP_N,
    min_score: float = DEFAULT_MIN_SCORE,
    decay_threshold: float = DEFAULT_DECAY_THRESHOLD,
    price_mode: str = "mid",
    dry_run: bool = True,
) -> dict:
    """Operational PMCC bot. Dry-run by default — set dry_run=False to place real orders.

    Phase 1 (manage): close+reroll bot-owned diagonal shorts that have decayed past
        ``decay_threshold``.
    Phase 2 (open): scan ``symbols``, pick the top-N highest-scoring diagonals that fit
        within available funds, and open them as combo orders.

    Only equity diagonal-call spreads are managed — the user's manual futures/stock
    positions are excluded by construction.
    """
    try:
        async with ib_connection(port, CLIENT_IDS["pmcc_advisor"]) as ib:
            ib.reqMarketDataType(4)
            await asyncio.sleep(1)

            managed = ib.managedAccounts()
            if account and account not in managed:
                return {
                    "generated_at": generated_at_str(),
                    "error": f"Account {account} not found. Available: {managed}",
                }
            acct = account or (managed[0] if managed else None)

            funds = await _available_funds(ib, acct) if acct else {}
            available = funds.get("available_funds") or funds.get("excess_liquidity") or 0.0

            # ---- Phase 1: manage existing bot-owned diagonals ----
            raw = await fetch_positions(ib, account=acct)
            normalized = normalize_positions(raw)
            spreads = _identify_pmcc_spreads(normalized)
            exit_actions = await _build_exit_actions(ib, spreads, decay_threshold, price_mode)

            # Symbols already held or with a working bot order — never opened again.
            held_symbols = {s["symbol"].upper() for s in spreads}
            pending_symbols = await _pending_bot_symbols(ib)
            exclude_symbols = held_symbols | pending_symbols

            # Safety: never place orders on stale prices outside US market hours. The
            # scanner uses delayed quotes; firing entries off-hours risks bad fills.
            live = is_trading_now()
            can_trade = (not dry_run) and live

            placed_closes_raw = []
            if can_trade:
                for a in exit_actions:
                    if a["action"] == "close_and_reroll" and a["limit_price"]:
                        res, trade = await _place_buy_to_close(
                            ib,
                            a["symbol"],
                            {
                                "expiry": a["short_expiry"],
                                "strike": a["short_strike"],
                                "limit_price": a["limit_price"],
                            },
                            a["qty"],
                            acct,
                        )
                        placed_closes_raw.append((res, trade))

            # ---- Phase 2: scan + open new diagonals ----
            candidates = await _scan_candidates(symbols)
            selected, skipped = select_entries(
                candidates, available, top_n, min_score, exclude_symbols=exclude_symbols
            )
            entry_plans = [build_entry_plan(c) for c in selected]

            placed_entries_raw = []
            if can_trade:
                for plan in entry_plans:
                    res, trade = await _place_diagonal_combo(ib, plan, acct)
                    placed_entries_raw.append((res, trade))

            # Confirm orders reached a stable status BEFORE the connection closes.
            placed_closes = await _confirm_statuses(ib, placed_closes_raw)
            placed_entries = await _confirm_statuses(ib, placed_entries_raw)

            committed = round(sum(p["entry_cost"] for p in entry_plans), 2)

            return {
                "generated_at": generated_at_str(),
                "data_delay": "real-time",
                "account": acct,
                "dry_run": dry_run,
                "market_open": live,
                "orders_placed": can_trade,
                "funds": funds,
                "policy": {
                    "top_n": top_n,
                    "min_score": min_score,
                    "decay_threshold_pct": round(decay_threshold * 100, 1),
                    "capital_gate": "available_funds",
                },
                "manage": {
                    "managed_diagonals": len(spreads),
                    "actions": exit_actions,
                    "placed_closes": placed_closes,
                },
                "open": {
                    "scanned": len(symbols),
                    "candidates_found": len(candidates),
                    "committed_capital": committed,
                    "available_funds": available,
                    "entries": entry_plans,
                    "skipped": [
                        {
                            "symbol": s["symbol"],
                            "score": s.get("pmcc_score"),
                            "reason": s["skip_reason"],
                        }
                        for s in skipped
                    ],
                    "placed_entries": placed_entries,
                },
            }

    except ConnectionError as e:
        return {
            "generated_at": generated_at_str(),
            "error": f"{e}. Is TWS/Gateway running?",
        }

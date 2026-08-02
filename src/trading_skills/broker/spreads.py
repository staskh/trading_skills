# ABOUTME: Groups raw option executions into consolidated legs and vertical spreads.
# ABOUTME: Requires open/close indicators, so it only works on FlexReport-sourced data.

from collections import defaultdict

# Groups that cannot be resolved into a clean vertical are returned untouched
# with one of these reasons rather than being force-fit into a bogus spread.
REASON_NO_OPEN = "closing legs with no matching open in range (opened before start_date)"
REASON_NO_CLOSE = "open legs with no matching close (position still open)"
REASON_ONE_SIDED = "only one side present — not a vertical (naked or single-leg)"
REASON_MULTI_STRIKE = "more than two open strikes — roll, condor on one side, or multiple verticals"
REASON_RATIO = "unequal short/long quantity — ratio spread, not a vertical"
REASON_NO_OPENCLOSE = "missing open/close indicator — source does not support spread grouping"


def consolidate_legs(executions: list[dict]) -> list[dict]:
    """Merge partial fills of the same order into one leg per minute.

    A single 18-lot order routed across five exchanges arrives as five executions.
    They are merged on account/date/expiry/strike/right/side/open-close/minute so the
    output reflects orders rather than fills. Price becomes the quantity-weighted average.
    """
    buckets: dict[tuple, dict] = defaultdict(
        lambda: {"qty": 0.0, "notional": 0.0, "comm": 0.0, "pnl": 0.0, "book": False}
    )
    order: list[tuple] = []

    for ex in executions:
        dt = ex.get("datetime") or ""
        key = (
            ex.get("account"),
            dt[:10],
            ex.get("expiry"),
            ex.get("strike"),
            ex.get("right"),
            ex.get("side"),
            ex.get("openClose"),
            dt[11:16],
        )
        if key not in buckets:
            order.append(key)
        b = buckets[key]
        qty = float(ex.get("quantity") or 0)
        b["qty"] += qty
        b["notional"] += qty * float(ex.get("price") or 0)
        b["comm"] += float(ex.get("commission") or 0)
        b["pnl"] += float(ex.get("realizedPnL") or 0)
        b["book"] = b["book"] or bool(ex.get("bookTrade"))
        b["multiplier"] = float(ex.get("multiplier") or 100)
        b["symbol"] = ex.get("symbol")

    legs = []
    for key in order:
        account, date, expiry, strike, right, side, open_close, hhmm = key
        b = buckets[key]
        legs.append(
            {
                "account": account,
                "symbol": b.get("symbol"),
                "date": date,
                "time": hhmm,
                "expiry": expiry,
                "strike": strike,
                "right": right,
                "side": side,
                "openClose": open_close,
                "quantity": b["qty"],
                "avgPrice": round(b["notional"] / b["qty"], 4) if b["qty"] else 0.0,
                # P&L and commission stay at full broker precision. Rounding each leg
                # and then summing accumulates cents across hundreds of legs and breaks
                # reconciliation against the raw executions; round once, at the spread.
                "commission": b["comm"],
                "realizedPnL": b["pnl"],
                "settled": b["book"],
                "multiplier": b.get("multiplier", 100),
            }
        )

    legs.sort(key=lambda x: (x["date"], x["time"], x["right"] or "", x["strike"] or 0))
    return legs


def group_into_spreads(executions: list[dict]) -> dict:
    """Pair consolidated legs into vertical credit/debit spreads.

    Legs are keyed on (account, symbol, expiry, right) rather than trade date, because a
    spread opened one day and settled the next would otherwise have its closing legs
    orphaned and its P&L dropped.

    Returns a dict with `spreads`, `legs`, `ungrouped`, and `warnings`. Anything that is
    not an unambiguous two-strike vertical is left in `ungrouped` with a reason — no
    guessing.
    """
    legs = consolidate_legs(executions)

    option_legs = [x for x in legs if x["right"] in ("C", "P")]
    non_option = [x for x in legs if x["right"] not in ("C", "P")]

    warnings: list[str] = []
    ungrouped: list[dict] = list(non_option)
    if non_option:
        warnings.append(f"{len(non_option)} non-option leg(s) skipped (not spread-eligible)")

    # No indicator anywhere means the source cannot support grouping at all (the live
    # API path). A single odd value (IBKR emits "C;O" for a trade that closes one
    # position and opens another) is handled per-group instead, so one strange row
    # cannot discard the whole report.
    if option_legs and all(x["openClose"] not in ("O", "C") for x in option_legs):
        return {
            "spreads": [],
            "legs": legs,
            "ungrouped": legs,
            "warnings": [REASON_NO_OPENCLOSE],
        }

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for leg in option_legs:
        groups[(leg["account"], leg["symbol"], leg["expiry"], leg["right"])].append(leg)

    spreads = []
    for (account, symbol, expiry, right), group in sorted(
        groups.items(), key=lambda kv: (str(kv[0][2]), str(kv[0][3]))
    ):
        opens = [g for g in group if g["openClose"] == "O"]
        closes = [g for g in group if g["openClose"] == "C"]

        reason = _reject_reason(opens, closes, group)
        if reason:
            ungrouped.extend(group)
            label = f"{symbol} {expiry} {right}"
            warnings.append(f"{label}: {reason}")
            continue

        shorts = [g for g in opens if g["side"] == "SLD"]
        longs = [g for g in opens if g["side"] == "BOT"]

        short_qty = sum(g["quantity"] for g in shorts)
        long_qty = sum(g["quantity"] for g in longs)
        short_px = sum(g["quantity"] * g["avgPrice"] for g in shorts) / short_qty
        long_px = sum(g["quantity"] * g["avgPrice"] for g in longs) / long_qty
        short_k = shorts[0]["strike"]
        long_k = longs[0]["strike"]

        credit = short_px - long_px
        width = abs(short_k - long_k)
        lots = short_qty
        multiplier = opens[0]["multiplier"]
        max_credit = credit * lots * multiplier
        risk = (width - credit) * lots * multiplier
        pnl = round(sum(g["realizedPnL"] for g in group), 2)
        commission = round(sum(g["commission"] for g in group), 2)

        spreads.append(
            {
                "account": account,
                "symbol": symbol,
                "expiry": expiry,
                "right": right,
                "type": _spread_type(right, credit),
                "short_strike": short_k,
                "long_strike": long_k,
                "width": width,
                "lots": lots,
                "leg_count": len(group),
                "credit": round(credit, 4),
                "entry_date": min(g["date"] for g in opens),
                "entry_time": min(g["time"] for g in opens),
                "exit_date": max((g["date"] for g in closes), default=None),
                "exit_time": max((g["time"] for g in closes), default=None),
                "max_credit": round(max_credit, 2),
                "max_risk": round(risk, 2),
                "realizedPnL": pnl,
                "commission": commission,
                "netPnL": round(pnl + commission, 2),
                "capture_pct": round(pnl / max_credit * 100, 2) if max_credit else None,
                "return_on_risk_pct": round(pnl / risk * 100, 2) if risk else None,
                "settled_at_expiry": any(g["settled"] for g in closes),
                "same_day": _same_day(min(g["date"] for g in opens), expiry),
            }
        )

    spreads.sort(key=lambda s: (s["entry_date"], s["entry_time"]))
    return {
        "spreads": spreads,
        "legs": legs,
        "ungrouped": ungrouped,
        "warnings": warnings,
    }


def _reject_reason(opens: list[dict], closes: list[dict], group: list[dict]) -> str | None:
    """Return why this group is not a clean vertical, or None if it is one."""
    if any(g["openClose"] not in ("O", "C") for g in group):
        return REASON_NO_OPENCLOSE
    if not opens:
        return REASON_NO_OPEN
    if not closes:
        return REASON_NO_CLOSE

    shorts = [g for g in opens if g["side"] == "SLD"]
    longs = [g for g in opens if g["side"] == "BOT"]
    if not shorts or not longs:
        return REASON_ONE_SIDED

    if len({g["strike"] for g in opens}) != 2:
        return REASON_MULTI_STRIKE
    if len({g["strike"] for g in shorts}) != 1 or len({g["strike"] for g in longs}) != 1:
        return REASON_MULTI_STRIKE

    short_qty = sum(g["quantity"] for g in shorts)
    long_qty = sum(g["quantity"] for g in longs)
    if abs(short_qty - long_qty) > 1e-9:
        return REASON_RATIO

    return None


def _spread_type(right: str, credit: float) -> str:
    """Name the structure from the option right and whether it was opened for a credit."""
    if right == "C":
        return "Bear call" if credit > 0 else "Bull call"
    return "Bull put" if credit > 0 else "Bear put"


def _same_day(entry_date: str, expiry: str) -> bool:
    """True when the spread expired the same session it was opened (0DTE)."""
    if not entry_date or not expiry:
        return False
    return entry_date.replace("-", "") == str(expiry).replace("-", "")

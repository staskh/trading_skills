# ABOUTME: Loads a previously saved 0DTE proposal and checks it against a fresh quote.
# ABOUTME: Execution references a reviewed spread rather than re-ranking the chain.

import json
from pathlib import Path

# A reviewed trade is only worth placing while it is still roughly the trade that
# was reviewed. Both tolerances are deliberately explicit — they decide whether a
# live order goes out, so they should be visible and overridable, not buried.
DEFAULT_MAX_CREDIT_DRIFT = 0.20  # refuse once the obtainable credit falls this far
DEFAULT_MAX_CUSHION_LOSS = 0.33  # refuse once this much of the spot-to-short room is gone

SANDBOX = Path(__file__).resolve().parents[3] / "sandbox"


class ProposalError(Exception):
    """A saved proposal could not be found or is not executable."""


def proposal_id_for(symbol: str, expiry: str, spread_type: str, stamp: str) -> str:
    """Stable handle for one run's proposal: symbol, expiry, type and run time."""
    return f"{symbol.upper()}-{expiry}-{spread_type}-{stamp}"


def load_proposal(ref: str, search_dir: Path | str | None = None) -> dict:
    """Load a saved run by file path, or by proposal id from the sandbox.

    Raises ProposalError when the reference matches nothing or the run holds no
    candidates — better to stop than to fall back to a different trade.
    """
    path = Path(ref)
    if path.is_file():
        proposal = json.loads(path.read_text())
    else:
        directory = Path(search_dir) if search_dir is not None else SANDBOX
        proposal = _find_by_id(ref, directory)

    if not proposal.get("candidates"):
        raise ProposalError(f"Proposal {ref} holds no candidates — nothing to execute.")
    return proposal


def _find_by_id(proposal_id: str, directory: Path) -> dict:
    """Scan saved runs for a matching proposal id, newest first."""
    for candidate_file in sorted(directory.glob("*.json"), reverse=True):
        try:
            data = json.loads(candidate_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("proposal_id") == proposal_id:
            data.setdefault("saved_to", str(candidate_file))
            return data
    raise ProposalError(f"No saved proposal {proposal_id!r} under {directory}.")


def _proposed_cushion(candidate: dict) -> float | None:
    """Spot-to-short room recorded at proposal time; the nearest side for a condor."""
    sides = [
        candidate.get("call_distance_to_short"),
        candidate.get("put_distance_to_short"),
    ]
    present = [s for s in sides if s is not None]
    if present:
        return min(present)
    return candidate.get("distance_to_short")


def _fresh_cushion(candidate: dict, fresh_spot: float) -> float | None:
    """Spot-to-short room now, measured against the same short leg(s)."""
    shorts = [leg["strike"] for leg in candidate["legs"] if leg["action"] == "sell"]
    if not shorts:
        return None
    return min(abs(fresh_spot - strike) for strike in shorts)


def check_drift(
    candidate: dict,
    *,
    fresh_credit: float | None,
    fresh_spot: float | None,
    max_credit_drift: float = DEFAULT_MAX_CREDIT_DRIFT,
    max_cushion_loss: float = DEFAULT_MAX_CUSHION_LOSS,
) -> dict:
    """Decide whether the market still offers the spread that was reviewed.

    Checks the credit actually obtainable now and how much of the spot-to-short
    cushion survives. A better credit never blocks; only erosion does.
    """
    proposed_credit = candidate.get("combo_ask_credit", candidate.get("net_credit"))
    proposed_cushion = _proposed_cushion(candidate)
    fresh_cushion = _fresh_cushion(candidate, fresh_spot) if fresh_spot is not None else None

    result = {
        "ok": True,
        "reason": None,
        "proposed_credit": proposed_credit,
        "fresh_credit": fresh_credit,
        "proposed_cushion": proposed_cushion,
        "fresh_cushion": fresh_cushion,
        "credit_drift": None,
        "cushion_loss": None,
        "max_credit_drift": max_credit_drift,
        "max_cushion_loss": max_cushion_loss,
    }

    if fresh_credit is None or fresh_spot is None:
        result["ok"] = False
        result["reason"] = (
            "No live quote for the proposed legs — cannot confirm the trade is still on offer."
        )
        return result

    if proposed_credit:
        drift = (proposed_credit - fresh_credit) / abs(proposed_credit)
        result["credit_drift"] = round(drift, 4)
        if drift > max_credit_drift:
            result["ok"] = False
            result["reason"] = (
                f"Credit fell from {proposed_credit:.2f} to {fresh_credit:.2f} "
                f"({drift:.0%} below the reviewed proposal, limit {max_credit_drift:.0%})."
            )
            return result

    if proposed_cushion and fresh_cushion is not None:
        loss = (proposed_cushion - fresh_cushion) / abs(proposed_cushion)
        result["cushion_loss"] = round(loss, 4)
        if loss > max_cushion_loss:
            result["ok"] = False
            result["reason"] = (
                f"Cushion to the short strike shrank from {proposed_cushion:.1f} to "
                f"{fresh_cushion:.1f} points ({loss:.0%} gone, limit {max_cushion_loss:.0%})."
            )
            return result

    return result


def combo_ask_credit(legs: list[dict], quotes: dict[tuple[str, float], dict]) -> float | None:
    """Marketable BUY-side credit for these legs: short bids minus long asks.

    Returns None if any leg has no live two-sided quote — an unquotable leg means
    the spread cannot be validated, and an unvalidated spread is not placed.
    """
    total = 0.0
    for leg in legs:
        quote = quotes.get((leg["right"], leg["strike"]))
        if quote is None:
            return None
        price = quote.get("bid") if leg["action"] == "sell" else quote.get("ask")
        if price is None:
            return None
        total += price if leg["action"] == "sell" else -price
    return round(total, 2)


async def execute_proposal(
    ref: str,
    *,
    port: int = 7496,
    account: str | None = None,
    pick: int = 1,
    limit: float | None = None,
    limit_frac: float | None = None,
    replace: bool = False,
    max_credit_drift: float = DEFAULT_MAX_CREDIT_DRIFT,
    max_cushion_loss: float = DEFAULT_MAX_CUSHION_LOSS,
    stop_mult: float | None = None,
    stop_buffer: float | None = None,
    stop_delta: float | None = None,
    profit_target: float | None = None,
    time_exit: str | None = None,
    fill_timeout: float = 60.0,
    rate: float | None = None,
    search_dir: Path | str | None = None,
) -> dict:
    """Place a spread that was proposed by an earlier run, after re-validating it.

    The legs come from the saved proposal, never from a fresh ranking, so the
    trade placed is the trade that was reviewed. A fresh quote for those exact
    legs decides whether it is still on offer; if the market has moved past the
    tolerances the order is refused rather than silently repriced.
    """
    from trading_skills.broker.connection import CLIENT_IDS, ib_connection
    from trading_skills.broker.zero_dte import (
        DEFAULT_RATE,
        INDEX_SPECS,
        _fetch_chain_sides,
        _maybe_execute,
        _select_chain,
        _time_to_expiry_years,
        _underlying_price,
        resolve_stop_cfg,
        resolve_underlying,
    )

    rate = DEFAULT_RATE if rate is None else rate

    try:
        proposal = load_proposal(ref, search_dir=search_dir)
    except ProposalError as exc:
        return {"success": False, "error": str(exc)}

    candidates = proposal["candidates"]
    if not 1 <= pick <= len(candidates):
        return {
            "success": False,
            "error": f"--pick {pick} out of range: the proposal holds {len(candidates)}.",
        }
    candidate = candidates[pick - 1]

    symbol = proposal["symbol"]
    expiry = proposal["expiry"]
    spread_type = proposal.get("spread_type") or candidate.get("strategy")
    contract, sec_type, asset_type = resolve_underlying(symbol)

    base = {
        "success": False,
        "symbol": symbol,
        "expiry": expiry,
        "spread_type": spread_type,
        "proposal_id": proposal.get("proposal_id"),
        "proposal_generated_at": proposal.get("generated_at"),
        "proposal_source": proposal.get("saved_to", ref),
        "picked": pick,
    }

    try:
        async with ib_connection(port, CLIENT_IDS["zero_dte"], readonly=False) as ib:
            ib.reqMarketDataType(4)

            managed = ib.managedAccounts()
            if account and managed and account not in managed:
                return {**base, "error": f"Account {account} not found. Available: {managed}"}
            trade_account = account or (managed[0] if len(managed) == 1 else None)
            if not trade_account:
                return {**base, "error": "--account is required when the login manages several."}

            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified or qualified[0] is None or not qualified[0].conId:
                return {**base, "error": f"Unknown symbol: {symbol}"}

            spot = await _underlying_price(ib, contract)
            if not spot or spot <= 0:
                return {**base, "error": f"Could not determine price for {symbol}"}

            chains = await ib.reqSecDefOptParamsAsync(symbol, "", sec_type, contract.conId)
            if not chains:
                return {**base, "error": f"No options found for {symbol}"}
            chain = _select_chain(chains, expiry)

            # Re-quote the proposal's own legs — not a fresh ranking of the chain.
            strikes = sorted({leg["strike"] for leg in candidate["legs"]})
            rights = {leg["right"] for leg in candidate["legs"]}
            T = _time_to_expiry_years(expiry)
            calls, puts = await _fetch_chain_sides(
                ib,
                symbol,
                expiry,
                strikes,
                chain.exchange,
                chain.tradingClass,
                spot,
                T,
                rate,
                False,
                need_calls="C" in rights,
                need_puts="P" in rights,
            )
            quotes = {(o["right"], o["strike"]): o for o in calls + puts}
            fresh_credit = combo_ask_credit(candidate["legs"], quotes)

            drift = check_drift(
                candidate,
                fresh_credit=fresh_credit,
                fresh_spot=spot,
                max_credit_drift=max_credit_drift,
                max_cushion_loss=max_cushion_loss,
            )
            base = {**base, "underlying_price": spot, "drift": drift, "account": trade_account}
            if not drift["ok"]:
                return {**base, "error": f"Proposal no longer valid: {drift['reason']}"}

            # Place the reviewed legs at the credit the market is showing now.
            priced = {**candidate, "combo_ask_credit": fresh_credit}
            order = await _maybe_execute(
                ib,
                [priced],
                1,
                trade_account,
                priced.get("capital_at_risk") or priced.get("max_loss_total"),
                limit,
                limit_frac,
                symbol,
                expiry,
                chain.exchange,
                chain.tradingClass,
                spread_type,
                replace=replace,
                spot=spot,
                T=T,
                rate=rate,
                underlying_conid=contract.conId,
                underlying_exch=INDEX_SPECS.get(symbol, "SMART"),
                stop_cfg=resolve_stop_cfg(
                    symbol,
                    stop_mult,
                    stop_buffer,
                    stop_delta,
                    fill_timeout,
                    target=profit_target,
                    time_exit=time_exit,
                ),
            )
            return {
                **base,
                "success": bool(order and order.get("ok")),
                "asset_type": asset_type,
                "order": order,
            }
    except ConnectionError as exc:
        return {**base, "error": str(exc)}

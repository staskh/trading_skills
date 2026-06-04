# ABOUTME: Helpers for futures + futures-options (FOP) contracts on IB.
# ABOUTME: Asset type and exchange are resolved from IB contract details (source of truth),
#          not a hardcoded symbol/exchange table; FOP tradingClass collisions are disambiguated.

from ib_async import ContFuture, Future, FuturesOption


def _pick_future_exchange(contracts: list) -> str | None:
    """Exchange of the nearest-expiry future among ``contracts`` (pure, testable).

    Returns None if no contract carries a usable expiry/exchange. All expiries of a
    given root normally share an exchange, so the nearest one is a safe representative.
    """
    futs = [
        c
        for c in contracts
        if c is not None
        and getattr(c, "lastTradeDateOrContractMonth", None)
        and getattr(c, "exchange", None)
    ]
    if not futs:
        return None
    nearest = min(futs, key=lambda c: c.lastTradeDateOrContractMonth)
    return nearest.exchange


async def detect_future_exchange(ib, symbol: str) -> str | None:
    """Return the exchange if ``symbol`` trades as a future on IB, else None.

    IB is the source of truth: we ask for FUT contract details for the bare symbol and
    read the exchange back. No hardcoded list of futures roots or exchanges.
    """
    try:
        details = await ib.reqContractDetailsAsync(Future(symbol.upper(), includeExpired=False))
    except Exception:
        return None
    return _pick_future_exchange([d.contract for d in details if d.contract is not None])


async def front_future(ib, symbol: str, exchange: str):
    """Qualified continuous front-month future for ``symbol`` on ``exchange`` (or None)."""
    fut = ContFuture(symbol.upper(), exchange=exchange)
    qualified = await ib.qualifyContractsAsync(fut)
    if not qualified or qualified[0] is None or not qualified[0].conId:
        return None
    return qualified[0]


async def resolve_fop_contracts(
    ib, symbol: str, expiry: str, strikes: list, right: str, exchange: str
) -> list:
    """Resolve concrete FuturesOption contracts for the given strikes on ``exchange``.

    IB returns multiple FOPs for the same (expiry, strike) when a standard monthly
    contract (``tradingClass == symbol``) and a weekly/daily contract (e.g. ``Q3D``)
    share an expiry date. ``qualifyContractsAsync`` cannot pick between them and leaves
    the contract unqualified (no conId), silently dropping the candidate. We instead
    expand each strike via ``reqContractDetailsAsync`` and select one concrete contract
    per strike, preferring the standard monthly class.
    """
    sym = symbol.upper()
    resolved = []
    for strike in strikes:
        base = FuturesOption(sym, expiry, strike, right, exchange=exchange)
        try:
            details = await ib.reqContractDetailsAsync(base)
        except Exception:
            details = []
        contracts = [d.contract for d in details if d.contract is not None]
        if not contracts:
            continue
        standard = [c for c in contracts if c.tradingClass == sym]
        resolved.append(standard[0] if standard else contracts[0])
    return resolved

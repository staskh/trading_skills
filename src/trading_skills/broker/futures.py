# ABOUTME: Shared helpers for futures + futures-options (FOP) contracts on IB.
# ABOUTME: Classifies futures symbols, builds continuous-future underlyings, and resolves
#          FuturesOption contracts disambiguating the tradingClass collision IB returns.

from ib_async import ContFuture, FuturesOption

# Futures root symbols and their primary exchange. Options on these are FOP, not OPT.
# Exchange matters: ContFuture/FuturesOption fail to qualify on the wrong exchange.
FUTURES_EXCHANGE = {
    # CME (equity index + FX)
    "NQ": "CME",
    "ES": "CME",
    "RTY": "CME",
    "MNQ": "CME",
    "MES": "CME",
    "M2K": "CME",
    "6E": "CME",
    "6J": "CME",
    "6B": "CME",
    "6A": "CME",
    "6C": "CME",
    # CBOT (equity index + rates)
    "YM": "CBOT",
    "MYM": "CBOT",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
    "ZT": "CBOT",
    # NYMEX (energy)
    "CL": "NYMEX",
    "NG": "NYMEX",
    "MCL": "NYMEX",
    # COMEX (metals)
    "GC": "COMEX",
    "SI": "COMEX",
    "HG": "COMEX",
    "MGC": "COMEX",
}

FUTURES_SYMBOLS = frozenset(FUTURES_EXCHANGE)


def is_futures(symbol: str) -> bool:
    """True if ``symbol`` is a known futures root (options are FOP, not OPT)."""
    return symbol.upper() in FUTURES_SYMBOLS


def futures_exchange(symbol: str) -> str:
    """Primary exchange for a futures root; defaults to CME for unknown roots."""
    return FUTURES_EXCHANGE.get(symbol.upper(), "CME")


def futures_underlying(symbol: str) -> ContFuture:
    """Continuous front-month future for ``symbol`` (resolves ambiguity to front month)."""
    sym = symbol.upper()
    return ContFuture(sym, exchange=futures_exchange(sym))


async def resolve_fop_contracts(ib, symbol: str, expiry: str, strikes: list, right: str) -> list:
    """Resolve concrete FuturesOption contracts for the given strikes.

    IB returns multiple FOPs for the same (expiry, strike) when a standard monthly
    contract (``tradingClass == symbol``) and a weekly/daily contract (e.g. ``Q3D``)
    share an expiry date. ``qualifyContractsAsync`` cannot pick between them and leaves
    the contract unqualified (no conId), silently dropping the candidate. We instead
    expand each strike via ``reqContractDetailsAsync`` and select one concrete contract
    per strike, preferring the standard monthly class.
    """
    sym = symbol.upper()
    exch = futures_exchange(sym)
    resolved = []
    for strike in strikes:
        base = FuturesOption(sym, expiry, strike, right, exchange=exch)
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

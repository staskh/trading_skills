# ABOUTME: Fetches option chain data from Interactive Brokers (equities/ETFs and futures).
# ABOUTME: Asset type/exchange come from IB contract details; chains include model Greeks.

import asyncio
import logging
import math

from ib_async import IB, Contract, Option, Stock

from trading_skills.broker.connection import CLIENT_IDS, best_option_chain, ib_connection
from trading_skills.broker.futures import (
    detect_future_exchange,
    front_future,
    resolve_fop_contracts,
)


def _clean(x, ndigits=4):
    """Round a float, mapping None/NaN to None."""
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    return round(x, ndigits)


def _extract_greeks(model_greeks) -> dict | None:
    """Pull delta/gamma/theta/vega/IV from an IB modelGreeks object (None-safe).

    Pure function so it is unit-testable without an IB connection.
    """
    if model_greeks is None:
        return None
    iv = getattr(model_greeks, "impliedVol", None)
    greeks = {
        "delta": _clean(getattr(model_greeks, "delta", None)),
        "gamma": _clean(getattr(model_greeks, "gamma", None)),
        "theta": _clean(getattr(model_greeks, "theta", None)),
        "vega": _clean(getattr(model_greeks, "vega", None)),
        "iv": round(iv * 100, 2) if iv is not None and not math.isnan(iv) else None,
    }
    # All-None greeks (IB returned an empty computation) -> treat as absent.
    if all(v is None for v in greeks.values()):
        return None
    return greeks


async def _resolve_underlying(ib: IB, symbol: str, sec_type: str | None) -> tuple:
    """Resolve the underlying contract and asset type.

    Returns ``(asset_type, qualified_contract, exchange)`` where asset_type is
    "future"/"stock" and exchange is the futures exchange (None for stocks).
    asset_type is "unknown" with a None contract when nothing resolves.

    ``sec_type`` is an optional caller override ("stk"/"fut"). When omitted, auto-detect
    prefers the **equity**: it tries a SMART stock first and only falls back to a future
    if no stock qualifies. This avoids misrouting equities that happen to have obscure
    single-stock futures (e.g. AAPL on MEXDER), while NQ/ES/GC/RTY — which have no SMART
    stock — resolve as futures. Tickers that are BOTH (e.g. ES=Eversource, CL=Colgate)
    default to the equity; pass ``sec_type="fut"`` to force the future.
    """
    want = (sec_type or "").lower()

    if want == "fut":
        exchange = await detect_future_exchange(ib, symbol)
        if not exchange:
            return "unknown", None, None
        contract = await front_future(ib, symbol, exchange)
        return ("future", contract, exchange) if contract else ("unknown", None, None)

    # Explicit "stk" or auto: try the equity first. A failed qualify for a futures
    # root (e.g. NQ) is expected, so suppress the ib_async "Error 200" noise.
    stock = Stock(symbol, "SMART", "USD")
    ib_logger = logging.getLogger("ib_async")
    prev_level = ib_logger.level
    ib_logger.setLevel(logging.CRITICAL)
    try:
        qualified = await ib.qualifyContractsAsync(stock)
    finally:
        ib_logger.setLevel(prev_level)
    if qualified and qualified[0] is not None and qualified[0].conId:
        return "stock", qualified[0], None
    if want == "stk":
        return "unknown", None, None

    # Auto fallback: no stock — try a future.
    exchange = await detect_future_exchange(ib, symbol)
    if exchange:
        contract = await front_future(ib, symbol, exchange)
        if contract:
            return "future", contract, exchange
    return "unknown", None, None


async def _sec_def_params(ib: IB, symbol: str, asset_type: str, contract: Contract, exchange):
    """reqSecDefOptParams for an already-qualified underlying."""
    if asset_type == "future":
        return await ib.reqSecDefOptParamsAsync(symbol.upper(), exchange, "FUT", contract.conId)
    return await ib.reqSecDefOptParamsAsync(symbol, "", "STK", contract.conId)


async def get_expiries(symbol: str, port: int = 7496, sec_type: str | None = None) -> dict:
    """Get available option expiration dates from IB (equity/ETF or futures)."""
    try:
        async with ib_connection(port, CLIENT_IDS["options_expiries"]) as ib:
            asset_type, contract, exchange = await _resolve_underlying(ib, symbol, sec_type)
            if contract is None:
                return {"success": False, "error": f"Unknown symbol: {symbol}"}

            chains = await _sec_def_params(ib, symbol, asset_type, contract, exchange)
            if not chains:
                return {"success": False, "error": f"No options found for {symbol}"}

            chain = best_option_chain(chains)
            return {
                "success": True,
                "symbol": symbol.upper(),
                "source": "ibkr",
                "asset_type": asset_type,
                "expiries": sorted(chain.expirations),
            }
    except ConnectionError as e:
        return {"success": False, "error": str(e)}


async def _underlying_price(ib: IB, contract) -> float | None:
    """Best-effort last/market price for an already-qualified underlying contract."""
    [ticker] = await ib.reqTickersAsync(contract)
    await asyncio.sleep(0.5)
    price = ticker.marketPrice()
    if price is None or math.isnan(price):
        price = ticker.close if ticker.close and not math.isnan(ticker.close) else None
    return price


async def get_option_chain(
    symbol: str, expiry: str, port: int = 7496, sec_type: str | None = None
) -> dict:
    """Fetch option chain for a specific expiration date from IB (equity/ETF or futures)."""
    try:
        async with ib_connection(port, CLIENT_IDS["options_chain"]) as ib:
            # Delayed-frozen data (type 4) returns last known values outside market hours.
            ib.reqMarketDataType(4)

            asset_type, underlying, exchange = await _resolve_underlying(ib, symbol, sec_type)
            if underlying is None:
                return {"success": False, "error": f"Unknown symbol: {symbol}"}
            futures = asset_type == "future"

            chains = await _sec_def_params(ib, symbol, asset_type, underlying, exchange)
            underlying_price = await _underlying_price(ib, underlying)

            if not chains:
                return {"success": False, "error": f"No options found for {symbol}"}

            chain = best_option_chain(chains)
            if expiry not in chain.expirations:
                return {"success": False, "error": f"Expiry {expiry} not available for {symbol}"}

            all_strikes = sorted(chain.strikes)
            # Filter strikes to ~50% around ATM to keep the qualify/quote round-trip bounded.
            if underlying_price:
                lo, hi = underlying_price * 0.5, underlying_price * 1.5
                strikes = [s for s in all_strikes if lo <= s <= hi]
            else:
                strikes = all_strikes

            ib_logger = logging.getLogger("ib_async")
            prev_level = ib_logger.level
            ib_logger.setLevel(logging.CRITICAL)
            try:
                if futures:
                    calls, puts = await asyncio.gather(
                        _fetch_fop_quotes(
                            ib, symbol, expiry, strikes, "C", underlying_price, exchange
                        ),
                        _fetch_fop_quotes(
                            ib, symbol, expiry, strikes, "P", underlying_price, exchange
                        ),
                    )
                else:
                    calls, puts = await asyncio.gather(
                        _fetch_quotes(ib, symbol, expiry, strikes, "C", underlying_price),
                        _fetch_quotes(ib, symbol, expiry, strikes, "P", underlying_price),
                    )
            finally:
                ib_logger.setLevel(prev_level)

            return {
                "success": True,
                "symbol": symbol.upper(),
                "source": "ibkr",
                "asset_type": asset_type,
                "expiry": expiry,
                "underlying_price": underlying_price,
                "calls": calls,
                "puts": puts,
            }
    except ConnectionError as e:
        return {"success": False, "error": str(e)}


def _quote_row(t, right: str, underlying_price: float, include_multiplier: bool) -> dict:
    """Build a quote dict from an IB ticker (shared by equity and futures paths)."""
    bid = t.bid if t.bid and t.bid > 0 else None
    ask = t.ask if t.ask and t.ask > 0 else None
    last = t.last if t.last and t.last > 0 else None
    volume = int(t.volume) if t.volume and t.volume >= 0 else None
    row = {
        "strike": t.contract.strike,
        "bid": _clean(bid, 2),
        "ask": _clean(ask, 2),
        "lastPrice": _clean(last, 2),
        "volume": volume,
        "openInterest": None,  # IB doesn't provide OI in real-time tickers
        "impliedVolatility": (
            round(t.modelGreeks.impliedVol * 100, 2)
            if t.modelGreeks and t.modelGreeks.impliedVol
            else None
        ),
        "greeks": _extract_greeks(t.modelGreeks),
        "inTheMoney": (
            (t.contract.strike < underlying_price)
            if right == "C"
            else (t.contract.strike > underlying_price)
        )
        if underlying_price
        else None,
    }
    if include_multiplier:
        mult = t.contract.multiplier
        row["multiplier"] = int(mult) if mult else None
    return row


async def _fetch_quotes(
    ib: IB, symbol: str, expiry: str, strikes: list, right: str, underlying_price: float
) -> list:
    """Fetch equity/ETF option quotes for all strikes at given expiry and right (C/P)."""
    contracts = [Option(symbol, expiry, strike, right, "SMART") for strike in strikes]

    try:
        qualified = await asyncio.wait_for(ib.qualifyContractsAsync(*contracts), timeout=15)
    except asyncio.TimeoutError:
        return []

    qualified = [c for c in qualified if c is not None and c.conId]
    if not qualified:
        return []

    try:
        tickers = await asyncio.wait_for(ib.reqTickersAsync(*qualified), timeout=30)
    except asyncio.TimeoutError:
        return []

    await asyncio.sleep(1)  # IB streams data asynchronously

    results = [
        _quote_row(t, right, underlying_price, include_multiplier=False)
        for t in tickers
        if t.contract is not None
    ]
    return sorted(results, key=lambda x: x["strike"])


async def _fetch_fop_quotes(
    ib: IB,
    symbol: str,
    expiry: str,
    strikes: list,
    right: str,
    underlying_price: float,
    exchange: str,
) -> list:
    """Fetch futures-option (FOP) quotes + model Greeks for all strikes at expiry/right."""
    qualified = await resolve_fop_contracts(ib, symbol, expiry, strikes, right, exchange)
    if not qualified:
        return []

    try:
        tickers = await asyncio.wait_for(ib.reqTickersAsync(*qualified), timeout=30)
    except asyncio.TimeoutError:
        return []

    await asyncio.sleep(1)  # IB streams data asynchronously

    results = [
        _quote_row(t, right, underlying_price, include_multiplier=True)
        for t in tickers
        if t.contract is not None
    ]
    return sorted(results, key=lambda x: x["strike"])

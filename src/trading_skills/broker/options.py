# ABOUTME: Fetches option chain data from Interactive Brokers.
# ABOUTME: Supports listing expiries and fetching full chains with quotes.

import asyncio
import logging
import math

from ib_async import IB, Option, Stock

from trading_skills.broker.connection import CLIENT_IDS, best_option_chain, ib_connection


async def get_expiries(symbol: str, port: int = 7496) -> dict:
    """Get available option expiration dates from IB."""
    try:
        async with ib_connection(port, CLIENT_IDS["options_expiries"]) as ib:
            stock = Stock(symbol, "SMART", "USD")
            qualified = await ib.qualifyContractsAsync(stock)
            if not qualified or qualified[0] is None or not qualified[0].conId:
                return {"success": False, "error": f"Unknown symbol: {symbol}"}

            chains = await ib.reqSecDefOptParamsAsync(symbol, "", "STK", stock.conId)
            if not chains:
                return {"success": False, "error": f"No options found for {symbol}"}

            chain = best_option_chain(chains)
            return {
                "success": True,
                "symbol": symbol.upper(),
                "source": "ibkr",
                "expiries": sorted(chain.expirations),
            }
    except ConnectionError as e:
        return {"success": False, "error": str(e)}


async def get_option_chain(symbol: str, expiry: str, port: int = 7496) -> dict:
    """Fetch option chain for a specific expiration date from IB."""
    try:
        async with ib_connection(port, CLIENT_IDS["options_chain"]) as ib:
            # Use delayed-frozen data (type 4) to get last known values outside market hours
            ib.reqMarketDataType(4)

            # Get underlying price
            stock = Stock(symbol, "SMART", "USD")
            await ib.qualifyContractsAsync(stock)
            [ticker] = await ib.reqTickersAsync(stock)
            await asyncio.sleep(0.5)
            price = ticker.marketPrice()
            if math.isnan(price):
                price = ticker.close if ticker.close and not math.isnan(ticker.close) else None
            underlying_price = price

            # Get available strikes
            chains = await ib.reqSecDefOptParamsAsync(symbol, "", "STK", stock.conId)
            if not chains:
                return {"success": False, "error": f"No options found for {symbol}"}

            chain = best_option_chain(chains)

            if expiry not in chain.expirations:
                return {"success": False, "error": f"Expiry {expiry} not available for {symbol}"}

            all_strikes = sorted(chain.strikes)

            # Filter strikes to reasonable range around ATM (50% each direction)
            if underlying_price:
                lo = underlying_price * 0.5
                hi = underlying_price * 1.5
                strikes = [s for s in all_strikes if lo <= s <= hi]
            else:
                strikes = all_strikes

            # Suppress ib_async warnings for non-existent strikes during qualification
            ib_logger = logging.getLogger("ib_async")
            prev_level = ib_logger.level
            ib_logger.setLevel(logging.CRITICAL)

            # Fetch calls and puts in parallel
            try:
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
                "expiry": expiry,
                "underlying_price": underlying_price,
                "calls": calls,
                "puts": puts,
            }
    except ConnectionError as e:
        return {"success": False, "error": str(e)}


async def _fetch_quotes(
    ib: IB, symbol: str, expiry: str, strikes: list, right: str, underlying_price: float
) -> list:
    """Fetch option quotes for all strikes at given expiry and right (C/P)."""
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

    # Allow data to arrive (IB streams data asynchronously)
    await asyncio.sleep(1)

    results = []
    for t in tickers:
        if t.contract is None:
            continue
        bid = t.bid if t.bid and t.bid > 0 else None
        ask = t.ask if t.ask and t.ask > 0 else None
        last = t.last if t.last and t.last > 0 else None
        volume = int(t.volume) if t.volume and t.volume >= 0 else None
        open_interest = None  # IB doesn't provide OI in real-time tickers

        # IV from model greeks if available
        iv = None
        if t.modelGreeks and t.modelGreeks.impliedVol:
            iv = round(t.modelGreeks.impliedVol * 100, 2)

        results.append(
            {
                "strike": t.contract.strike,
                "bid": round(bid, 2) if bid is not None else None,
                "ask": round(ask, 2) if ask is not None else None,
                "lastPrice": round(last, 2) if last is not None else None,
                "volume": volume,
                "openInterest": open_interest,
                "impliedVolatility": iv,
                "inTheMoney": (
                    t.contract.strike < underlying_price
                    if right == "C"
                    else t.contract.strike > underlying_price
                ),
            }
        )

    return sorted(results, key=lambda x: x["strike"])

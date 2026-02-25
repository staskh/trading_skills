# ABOUTME: Shared IB connection utilities used by all broker modules.
# ABOUTME: Provides context manager, position fetching, normalization, and spot price helpers.

import asyncio
from contextlib import asynccontextmanager

from ib_async import IB, Stock

from trading_skills.utils import fetch_with_timeout

# Documented clientId allocation — one source of truth for all broker modules.
CLIENT_IDS = {
    "portfolio": 1,
    "account": 2,
    "collar": 3,
    "portfolio_action": 11,
    "delta_exposure": 10,
    "options_expiries": 20,
    "options_chain": 21,
    "roll": 30,
    "consolidate": 99,
}


@asynccontextmanager
async def ib_connection(port: int, client_id: int):
    """Connect to IB, yield the IB instance, disconnect on exit.

    Raises ConnectionError if the initial connection fails.
    """
    ib = IB()
    try:
        await ib.connectAsync(host="127.0.0.1", port=port, clientId=client_id)
    except Exception as e:
        raise ConnectionError(
            f"Could not connect to IB on port {port}: {e}"
        ) from e

    try:
        yield ib
    finally:
        ib.disconnect()


async def fetch_positions(ib: IB, account: str | None = None, sleep: float = 2) -> list:
    """Fetch raw IB Position objects, optionally filtered by account."""
    await asyncio.sleep(sleep)
    positions = ib.positions()
    if account:
        positions = [p for p in positions if p.account == account]
    return positions


def normalize_positions(raw_positions: list) -> list[dict]:
    """Convert raw IB Position objects to plain dicts.

    Divides avgCost by multiplier for OPT/FOP contracts.
    """
    result = []
    for pos in raw_positions:
        c = pos.contract
        multiplier = int(c.multiplier) if c.multiplier else 100
        entry = {
            "account": pos.account,
            "symbol": c.symbol,
            "sec_type": c.secType,
            "quantity": pos.position,
            "avg_cost": pos.avgCost,
        }
        if c.secType in ("OPT", "FOP"):
            entry.update({
                "strike": c.strike,
                "expiry": c.lastTradeDateOrContractMonth,
                "right": c.right,
                "avg_cost": pos.avgCost / multiplier,
            })
        result.append(entry)
    return result


async def fetch_spot_prices(
    ib: IB, symbols: list[str], timeout: float = 15.0
) -> dict[str, float]:
    """Fetch spot prices for stock symbols. Returns {symbol: price} dict."""
    if not symbols:
        return {}

    stock_contracts = [Stock(sym, "SMART", "USD") for sym in symbols]
    qualified = await fetch_with_timeout(
        ib.qualifyContractsAsync(*stock_contracts), timeout=timeout, default=[]
    )
    if not qualified:
        return {}

    tickers = await fetch_with_timeout(
        ib.reqTickersAsync(*qualified), timeout=timeout, default=[]
    )

    prices = {}
    for ticker in tickers or []:
        price = ticker.marketPrice()
        if price and price > 0:
            prices[ticker.contract.symbol] = price
    return prices

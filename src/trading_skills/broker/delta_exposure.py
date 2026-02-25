# ABOUTME: Calculates delta-adjusted notional exposure for IBKR portfolio.
# ABOUTME: Uses Black-Scholes for option deltas, reports by account and underlying.

import asyncio
from datetime import date, datetime

from ib_async import Stock

from trading_skills.black_scholes import black_scholes_delta, estimate_iv
from trading_skills.broker.connection import CLIENT_IDS, fetch_positions, ib_connection
from trading_skills.utils import fetch_with_timeout


async def get_delta_exposure(port: int = 7496):
    """Fetch portfolio and calculate delta-adjusted notional."""
    try:
        return await _get_delta_exposure(port)
    except ConnectionError as e:
        return {
            "connected": False,
            "error": f"{e}. Is TWS/Gateway running?",
        }


async def _get_delta_exposure(port: int):
    """Internal implementation with connection context manager."""
    async with ib_connection(port, CLIENT_IDS["delta_exposure"]) as ib:
        managed = ib.managedAccounts()

        all_positions = []
        for acct in managed:
            all_positions.extend(await fetch_positions(ib, account=acct))

        # Separate by type
        option_positions = [p for p in all_positions if p.contract.secType == "OPT"]
        fut_opt_positions = [p for p in all_positions if p.contract.secType == "FOP"]
        future_positions = [p for p in all_positions if p.contract.secType == "FUT"]
        stock_positions = [p for p in all_positions if p.contract.secType == "STK"]

        # Get underlying prices for equity options
        underlying_symbols = {p.contract.symbol for p in option_positions}
        spot_prices = {}

        if underlying_symbols:
            stock_contracts = []
            for sym in underlying_symbols:
                try:
                    stock_contracts.append(Stock(sym, "SMART", "USD"))
                except Exception:
                    pass

            if stock_contracts:
                qualified = await fetch_with_timeout(
                    ib.qualifyContractsAsync(*stock_contracts), timeout=30.0, default=[]
                )
                if qualified:
                    for i in range(0, len(qualified), 20):
                        batch = qualified[i : i + 20]
                        tickers = await fetch_with_timeout(
                            ib.reqTickersAsync(*batch), timeout=30.0, default=[]
                        )
                        for ticker in tickers or []:
                            price = ticker.marketPrice()
                            if price and price > 0:
                                spot_prices[ticker.contract.symbol] = price
                        await asyncio.sleep(0.5)

        today = date.today()
        results = []

        # Process equity options
        for pos in option_positions:
            c = pos.contract
            symbol = c.symbol
            spot = spot_prices.get(symbol)
            if not spot:
                spot = c.strike * 0.95  # Fallback estimate

            strike = c.strike
            expiry_str = c.lastTradeDateOrContractMonth
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d").date()
            dte = (expiry_date - today).days
            dte_years = max(dte / 365.0, 0.001)

            is_call = c.right == "C"
            multiplier = int(c.multiplier) if c.multiplier else 100
            qty = pos.position

            option_type = "call" if is_call else "put"
            iv = estimate_iv(spot, strike, dte_years, option_type)
            delta = black_scholes_delta(spot, strike, dte_years, 0.05, iv, option_type)

            delta_notional = delta * spot * qty * multiplier
            raw_notional = spot * qty * multiplier

            results.append(
                {
                    "account": pos.account,
                    "symbol": symbol,
                    "sec_type": "OPT",
                    "strike": strike,
                    "expiry": expiry_str,
                    "right": c.right,
                    "qty": qty,
                    "spot": round(spot, 2),
                    "delta": round(delta, 4),
                    "multiplier": multiplier,
                    "raw_notional": round(raw_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Process futures options (FOP)
        for pos in fut_opt_positions:
            c = pos.contract
            symbol = c.symbol
            strike = c.strike
            expiry_str = c.lastTradeDateOrContractMonth
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d").date()
            dte = (expiry_date - today).days
            dte_years = max(dte / 365.0, 0.001)

            is_call = c.right == "C"
            multiplier = int(c.multiplier) if c.multiplier else 20
            qty = pos.position

            # Estimate futures spot from symbol
            spot = 21500 if symbol == "NQ" else 5000 if symbol == "ES" else strike

            iv = 0.20  # Lower IV for index futures
            option_type = "call" if is_call else "put"
            delta = black_scholes_delta(spot, strike, dte_years, 0.05, iv, option_type)

            delta_notional = delta * spot * qty * multiplier
            raw_notional = spot * qty * multiplier

            results.append(
                {
                    "account": pos.account,
                    "symbol": symbol,
                    "sec_type": "FOP",
                    "strike": strike,
                    "expiry": expiry_str,
                    "right": c.right,
                    "qty": qty,
                    "spot": spot,
                    "delta": round(delta, 4),
                    "multiplier": multiplier,
                    "raw_notional": round(raw_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Process futures (delta = 1)
        for pos in future_positions:
            c = pos.contract
            multiplier = int(c.multiplier) if c.multiplier else 20
            qty = pos.position
            avg_cost = pos.avgCost
            spot = avg_cost / multiplier if multiplier else avg_cost

            delta_notional = spot * qty * multiplier

            results.append(
                {
                    "account": pos.account,
                    "symbol": c.symbol,
                    "sec_type": "FUT",
                    "qty": qty,
                    "spot": round(spot, 2),
                    "delta": 1.0,
                    "multiplier": multiplier,
                    "raw_notional": round(delta_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Process stocks (delta = 1)
        for pos in stock_positions:
            c = pos.contract
            spot = spot_prices.get(c.symbol, pos.avgCost)
            qty = pos.position

            delta_notional = spot * qty

            results.append(
                {
                    "account": pos.account,
                    "symbol": c.symbol,
                    "sec_type": "STK",
                    "qty": qty,
                    "spot": round(spot, 2),
                    "delta": 1.0,
                    "multiplier": 1,
                    "raw_notional": round(delta_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Calculate summaries
        long_delta_notional = sum(p["delta_notional"] for p in results if p["delta_notional"] > 0)
        short_delta_notional = sum(p["delta_notional"] for p in results if p["delta_notional"] < 0)

        # By account
        account_summary = {}
        for p in results:
            acct = p["account"]
            if acct not in account_summary:
                account_summary[acct] = {"long": 0, "short": 0}
            if p["delta_notional"] > 0:
                account_summary[acct]["long"] += p["delta_notional"]
            else:
                account_summary[acct]["short"] += p["delta_notional"]

        # By underlying
        underlying_summary = {}
        for p in results:
            sym = p["symbol"]
            if sym not in underlying_summary:
                underlying_summary[sym] = {"long": 0, "short": 0}
            if p["delta_notional"] > 0:
                underlying_summary[sym]["long"] += p["delta_notional"]
            else:
                underlying_summary[sym]["short"] += p["delta_notional"]

        return {
            "connected": True,
            "accounts": managed,
            "position_count": len(results),
            "positions": results,
            "summary": {
                "total_long_delta_notional": round(long_delta_notional, 2),
                "total_short_delta_notional": round(short_delta_notional, 2),
                "net_delta_notional": round(long_delta_notional + short_delta_notional, 2),
                "by_account": {
                    k: {"long": round(v["long"], 2), "short": round(v["short"], 2)}
                    for k, v in account_summary.items()
                },
                "by_underlying": {
                    k: {
                        "long": round(v["long"], 2),
                        "short": round(v["short"], 2),
                        "net": round(v["long"] + v["short"], 2),
                    }
                    for k, v in underlying_summary.items()
                },
            },
        }

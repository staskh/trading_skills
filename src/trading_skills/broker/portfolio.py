# ABOUTME: Fetches portfolio positions from Interactive Brokers.
# ABOUTME: Requires TWS or IB Gateway running locally.

import asyncio

from ib_async import IB, Stock

from trading_skills.utils import fetch_with_timeout


async def get_portfolio(port: int = 7496, account: str = None, all_accounts: bool = False) -> dict:
    """Fetch portfolio positions from IB."""
    ib = IB()

    try:
        await ib.connectAsync(host="127.0.0.1", port=port, clientId=1)
    except Exception as e:
        return {
            "connected": False,
            "error": f"Could not connect to IB on port {port}. Is TWS/Gateway running? Error: {e}",
        }

    # Validate account selection
    managed = ib.managedAccounts()

    if all_accounts:
        accounts_to_fetch = managed
    elif account:
        if account not in managed:
            ib.disconnect()
            return {
                "connected": True,
                "error": f"Account {account} not found. Available accounts: {managed}",
            }
        accounts_to_fetch = [account]
    else:
        accounts_to_fetch = [managed[0]] if managed else []

    try:
        # Wait for position data to sync
        await asyncio.sleep(2)

        # Use positions() which returns data faster than portfolio()
        all_positions = []
        for acct in accounts_to_fetch:
            acct_positions = ib.positions(account=acct)
            all_positions.extend(acct_positions)

        # Separate options and other positions
        option_positions = [p for p in all_positions if p.contract.secType == "OPT"]
        other_positions = [p for p in all_positions if p.contract.secType != "OPT"]

        # Collect unique underlying symbols from options for spot prices
        underlying_symbols = {p.contract.symbol for p in option_positions}

        # Fetch spot prices for underlyings
        spot_prices = {}
        if underlying_symbols:
            stock_contracts = [Stock(sym, "SMART", "USD") for sym in underlying_symbols]
            qualified = await fetch_with_timeout(
                ib.qualifyContractsAsync(*stock_contracts), timeout=15.0, default=[]
            )
            if qualified:
                tickers = await fetch_with_timeout(
                    ib.reqTickersAsync(*qualified), timeout=15.0, default=[]
                )
                for ticker in tickers or []:
                    price = ticker.marketPrice()
                    if price and price > 0:
                        spot_prices[ticker.contract.symbol] = round(price, 2)

        # Fetch market prices for option contracts
        option_prices = {}
        if option_positions:
            option_contracts = [p.contract for p in option_positions]
            qualified_opts = await fetch_with_timeout(
                ib.qualifyContractsAsync(*option_contracts), timeout=15.0, default=[]
            )
            if qualified_opts:
                opt_tickers = await fetch_with_timeout(
                    ib.reqTickersAsync(*qualified_opts), timeout=15.0, default=[]
                )
                for ticker in opt_tickers or []:
                    c = ticker.contract
                    key = (c.symbol, c.strike, c.lastTradeDateOrContractMonth, c.right)
                    price = ticker.marketPrice()
                    if price and price > 0:
                        option_prices[key] = round(price, 2)

        pos_list = []

        # Process non-option positions
        for pos in other_positions:
            contract = pos.contract
            pos_list.append(
                {
                    "account": pos.account,
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "currency": contract.currency,
                    "quantity": pos.position,
                    "avg_cost": round(pos.avgCost, 2),
                }
            )

        # Process option positions
        for pos in option_positions:
            contract = pos.contract
            multiplier = int(contract.multiplier) if contract.multiplier else 100
            key = (
                contract.symbol,
                contract.strike,
                contract.lastTradeDateOrContractMonth,
                contract.right,
            )
            market_price = option_prices.get(key)

            entry = {
                "account": pos.account,
                "symbol": contract.symbol,
                "sec_type": contract.secType,
                "currency": contract.currency,
                "quantity": pos.position,
                "avg_cost": round(pos.avgCost / multiplier, 2),
                "strike": contract.strike,
                "expiry": contract.lastTradeDateOrContractMonth,
                "right": contract.right,
                "underlying_price": spot_prices.get(contract.symbol),
            }
            if market_price:
                entry["market_price"] = market_price
                entry["market_value"] = round(market_price * abs(pos.position) * multiplier, 2)
                entry["unrealized_pnl"] = round(
                    (market_price - pos.avgCost / multiplier) * pos.position * multiplier, 2
                )
            pos_list.append(entry)

        return {
            "connected": True,
            "accounts": accounts_to_fetch,
            "position_count": len(pos_list),
            "positions": pos_list,
        }

    finally:
        ib.disconnect()

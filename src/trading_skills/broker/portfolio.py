# ABOUTME: Fetches portfolio positions from Interactive Brokers.
# ABOUTME: Requires TWS or IB Gateway running locally.

from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_positions,
    fetch_spot_prices,
    ib_connection,
)
from trading_skills.utils import fetch_with_timeout


async def get_portfolio(port: int = 7496, account: str = None, all_accounts: bool = False) -> dict:
    """Fetch portfolio positions from IB."""
    try:
        async with ib_connection(port, CLIENT_IDS["portfolio"]) as ib:
            # Validate account selection
            managed = ib.managedAccounts()

            if all_accounts:
                accounts_to_fetch = managed
            elif account:
                if account not in managed:
                    return {
                        "connected": True,
                        "error": f"Account {account} not found. Available accounts: {managed}",
                    }
                accounts_to_fetch = [account]
            else:
                accounts_to_fetch = [managed[0]] if managed else []

            # Fetch raw positions
            all_positions = []
            for acct in accounts_to_fetch:
                all_positions.extend(await fetch_positions(ib, account=acct))

            # Separate options and other positions
            option_positions = [p for p in all_positions if p.contract.secType == "OPT"]
            other_positions = [p for p in all_positions if p.contract.secType != "OPT"]

            # Fetch spot prices for underlyings
            underlying_symbols = {p.contract.symbol for p in option_positions}
            spot_prices = await fetch_spot_prices(ib, list(underlying_symbols))
            spot_prices = {k: round(v, 2) for k, v in spot_prices.items()}

            # Fetch market prices for option contracts (module-specific)
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

    except ConnectionError as e:
        return {
            "connected": False,
            "error": f"{e}. Is TWS/Gateway running?",
        }

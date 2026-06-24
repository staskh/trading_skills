# ABOUTME: Fetches portfolio positions from Interactive Brokers.
# ABOUTME: Requires TWS or IB Gateway running locally.


from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_spot_prices,
    ib_connection,
)


async def get_portfolio(port: int = 7496, account: str = None, all_accounts: bool = False) -> dict:
    """Fetch portfolio positions from IB.

    Uses ib.portfolio() (PortfolioItem objects from accountUpdates) for market prices
    instead of reqTickersAsync, which requires a paid market-data subscription.
    PortfolioItem includes marketPrice, marketValue, unrealizedPNL without any subscription.
    """
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

            # Subscribe to account updates for each account to populate ib.portfolio().
            # reqAccountUpdatesAsync sends reqAccountUpdates(True, account) and waits for
            # the initial accountDownloadEnd — after which ib.portfolio() is fully populated.
            # This is the only path that provides marketPrice/marketValue/unrealizedPNL
            # without a paid market-data subscription (data comes from TWS internal valuation).
            for acct in accounts_to_fetch:
                await ib.reqAccountUpdatesAsync(acct)

            portfolio_items = [
                item
                for item in ib.portfolio()
                if not accounts_to_fetch or item.account in accounts_to_fetch
            ]

            # Build a lookup: (symbol, strike, expiry, right) -> PortfolioItem for options
            portfolio_by_key: dict[tuple, object] = {}
            for item in portfolio_items:
                c = item.contract
                if c.secType == "OPT":
                    key = (c.symbol, c.strike, c.lastTradeDateOrContractMonth, c.right)
                    portfolio_by_key[key] = item

            # Separate options to fetch underlying spot prices
            opt_items = [item for item in portfolio_items if item.contract.secType == "OPT"]
            underlying_symbols = list({item.contract.symbol for item in opt_items})
            spot_prices = await fetch_spot_prices(ib, underlying_symbols)
            spot_prices = {k: round(v, 2) for k, v in spot_prices.items()}

            pos_list = []
            for item in portfolio_items:
                contract = item.contract
                multiplier = int(contract.multiplier) if contract.multiplier else 100
                if contract.secType in ("OPT", "FOP"):
                    avg_cost_per_share = round(item.averageCost / multiplier, 2)
                else:
                    avg_cost_per_share = round(item.averageCost, 2)

                entry = {
                    "account": item.account,
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "currency": contract.currency,
                    "quantity": item.position,
                    "avg_cost": avg_cost_per_share,
                }

                if contract.secType in ("OPT", "FOP"):
                    entry.update(
                        {
                            "strike": contract.strike,
                            "expiry": contract.lastTradeDateOrContractMonth,
                            "right": contract.right,
                            "underlying_price": spot_prices.get(contract.symbol),
                        }
                    )

                # marketPrice comes from accountUpdates — available without subscription
                mp = item.marketPrice
                if mp and mp > 0 and abs(mp) < 1e6:
                    entry["market_price"] = round(mp, 2)
                    entry["market_value"] = round(item.marketValue, 2)
                    entry["unrealized_pnl"] = round(item.unrealizedPNL, 2)

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

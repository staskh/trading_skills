# ABOUTME: Fetches portfolio positions from Questrade. Read-only.
# ABOUTME: Mirrors the shape of the IB get_portfolio output where it makes sense.

from questrade_skills.connection import get_accounts, qt_get


def _normalize_position(pos: dict, account: str) -> dict:
    """Map a Questrade position row to the skill's common position shape.

    Questrade does not split sec_type the way IB does; options come back with
    the option symbol in `symbol`. We pass through the fields the report
    skills actually consume and keep raw extras under their QT names.
    """
    return {
        "account": account,
        "symbol": pos.get("symbol"),
        "symbol_id": pos.get("symbolId"),
        "quantity": pos.get("openQuantity"),
        "avg_cost": pos.get("averageEntryPrice"),
        "market_price": pos.get("currentPrice"),
        "market_value": pos.get("currentMarketValue"),
        "total_cost": pos.get("totalCost"),
        "unrealized_pnl": pos.get("openPnl"),
        "is_under_reorg": pos.get("isUnderReorg", False),
    }


def get_portfolio(account: str | None = None, all_accounts: bool = False) -> dict:
    """Fetch positions from Questrade."""
    try:
        accounts = get_accounts()
        if not accounts:
            return {"connected": True, "error": "No accounts found on this login"}

        numbers = [a["number"] for a in accounts]
        if all_accounts:
            targets = numbers
        elif account:
            if account not in numbers:
                return {
                    "connected": True,
                    "error": f"Account {account} not found. Available: {numbers}",
                }
            targets = [account]
        else:
            targets = [numbers[0]]

        pos_list = []
        for num in targets:
            data = qt_get(f"/v1/accounts/{num}/positions")
            for p in data.get("positions", []):
                pos_list.append(_normalize_position(p, num))

        return {
            "connected": True,
            "accounts": targets,
            "position_count": len(pos_list),
            "positions": pos_list,
        }

    except ConnectionError as e:
        return {"connected": False, "error": str(e)}

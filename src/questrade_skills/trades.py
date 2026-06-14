# ABOUTME: Fetches order and execution history from Questrade. Read-only.
# ABOUTME: Analog to broker/trades.py (IB). No order placement.

from questrade_skills.connection import get_accounts, qt_get


def _normalize_order(o: dict, account: str) -> dict:
    return {
        "account": account,
        "id": o.get("id"),
        "symbol": o.get("symbol"),
        "side": o.get("side"),
        "order_type": o.get("orderType"),
        "state": o.get("state"),
        "quantity": o.get("totalQuantity"),
        "filled": o.get("filledQuantity"),
        "limit_price": o.get("limitPrice"),
        "stop_price": o.get("stopPrice"),
        "avg_exec_price": o.get("avgExecPrice"),
        "creation_time": o.get("creationTime"),
        "update_time": o.get("updateTime"),
    }


def get_orders(
    account: str | None = None,
    all_accounts: bool = False,
    start_time: str | None = None,
    end_time: str | None = None,
    state_filter: str | None = None,
) -> dict:
    """Fetch orders from Questrade.

    Args:
        start_time / end_time: ISO 8601 strings. Questrade requires a window;
            if omitted it returns open orders only.
        state_filter: e.g. 'All', 'Open', 'Closed'.
    """
    try:
        accounts = get_accounts()
        if not accounts:
            return {"connected": True, "error": "No accounts found on this login"}
        numbers = [a["number"] for a in accounts]
        targets = numbers if all_accounts else [account] if account else [numbers[0]]

        params = {}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        if state_filter:
            params["stateFilter"] = state_filter

        orders = []
        for num in targets:
            data = qt_get(f"/v1/accounts/{num}/orders", params=params)
            for o in data.get("orders", []):
                orders.append(_normalize_order(o, num))

        return {
            "connected": True,
            "accounts": targets,
            "order_count": len(orders),
            "orders": orders,
        }
    except ConnectionError as e:
        return {"connected": False, "error": str(e)}


def get_executions(
    account: str | None = None,
    all_accounts: bool = False,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict:
    """Fetch executions (fills) from Questrade for a time window."""
    try:
        accounts = get_accounts()
        if not accounts:
            return {"connected": True, "error": "No accounts found on this login"}
        numbers = [a["number"] for a in accounts]
        targets = numbers if all_accounts else [account] if account else [numbers[0]]

        params = {}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        fills = []
        for num in targets:
            data = qt_get(f"/v1/accounts/{num}/executions", params=params)
            for e in data.get("executions", []):
                fills.append(
                    {
                        "account": num,
                        "symbol": e.get("symbol"),
                        "side": e.get("side"),
                        "quantity": e.get("quantity"),
                        "price": e.get("price"),
                        "commission": e.get("commission"),
                        "time": e.get("timestamp"),
                    }
                )

        return {
            "connected": True,
            "accounts": targets,
            "execution_count": len(fills),
            "executions": fills,
        }
    except ConnectionError as e:
        return {"connected": False, "error": str(e)}

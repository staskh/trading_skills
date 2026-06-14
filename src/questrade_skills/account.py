# ABOUTME: Fetches account summary (balances) from Questrade.
# ABOUTME: Read-only. Mirrors the shape of the IB get_account_summary output.

from questrade_skills.connection import get_accounts, qt_get


def _summarize_balances(balances: dict) -> dict:
    """Pull the per-currency + combined balances into a compact summary.

    Questrade returns perCurrencyBalances (CAD and USD rows) and
    combinedBalances. We surface CAD/USD cash plus the combined totals.
    """
    per = {b["currency"]: b for b in balances.get("perCurrencyBalances", [])}
    combined = {b["currency"]: b for b in balances.get("combinedBalances", [])}
    # Prefer CAD combined view as the headline; fall back to first available.
    headline = combined.get("CAD") or next(iter(combined.values()), {})
    return {
        "currency": headline.get("currency"),
        "total_equity": headline.get("totalEquity"),
        "cash": headline.get("cash"),
        "market_value": headline.get("marketValue"),
        "buying_power": headline.get("buyingPower"),
        "maintenance_excess": headline.get("maintenanceExcess"),
        "per_currency": {
            cur: {
                "cash": row.get("cash"),
                "market_value": row.get("marketValue"),
                "total_equity": row.get("totalEquity"),
            }
            for cur, row in per.items()
        },
    }


def get_account_summary(account: str | None = None, all_accounts: bool = False) -> dict:
    """Fetch account summary from Questrade.

    Args:
        account: specific account number. If None, first account.
        all_accounts: if True, summarize every account on the login.
    """
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

        results = []
        for num in targets:
            balances = qt_get(f"/v1/accounts/{num}/balances")
            results.append({"account": num, "summary": _summarize_balances(balances)})

        return {"connected": True, "accounts": results}

    except ConnectionError as e:
        return {"connected": False, "error": str(e)}

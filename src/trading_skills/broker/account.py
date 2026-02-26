# ABOUTME: Fetches account summary from Interactive Brokers.
# ABOUTME: Supports single account, specific account, or all managed accounts.

from trading_skills.broker.connection import CLIENT_IDS, ib_connection


def _parse_account_summary(summary) -> dict:
    """Parse IB account summary items into a structured dict."""
    summary_dict = {}
    for item in summary:
        summary_dict[item.tag] = {
            "value": item.value,
            "currency": item.currency,
        }

    return {
        "summary": {
            "net_liquidation": summary_dict.get("NetLiquidation", {}).get("value"),
            "total_cash": summary_dict.get("TotalCashValue", {}).get("value"),
            "buying_power": summary_dict.get("BuyingPower", {}).get("value"),
            "available_funds": summary_dict.get("AvailableFunds", {}).get("value"),
            "excess_liquidity": summary_dict.get("ExcessLiquidity", {}).get("value"),
            "gross_position_value": summary_dict.get("GrossPositionValue", {}).get("value"),
            "maintenance_margin": summary_dict.get("MaintMarginReq", {}).get("value"),
            "unrealized_pnl": summary_dict.get("UnrealizedPnL", {}).get("value"),
            "realized_pnl": summary_dict.get("RealizedPnL", {}).get("value"),
        },
        "currency": summary_dict.get("NetLiquidation", {}).get("currency", "USD"),
    }


async def get_account_summary(
    port: int = 7496, account: str = None, all_accounts: bool = False
) -> dict:
    """Fetch account summary from IB.

    Args:
        port: IB Gateway/TWS port.
        account: Specific account ID to fetch. If not provided, fetches first account.
        all_accounts: If True, fetch summaries for all managed accounts.
    """
    try:
        async with ib_connection(port, CLIENT_IDS["account"]) as ib:
            managed = ib.managedAccounts()
            if not managed:
                return {"connected": True, "error": "No managed accounts found"}

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
                accounts_to_fetch = [managed[0]]

            results = []
            for account_id in accounts_to_fetch:
                summary = await ib.accountSummaryAsync(account_id)
                parsed = _parse_account_summary(summary)
                results.append(
                    {
                        "account": account_id,
                        **parsed,
                    }
                )

            return {
                "connected": True,
                "accounts": results,
            }

    except ConnectionError as e:
        return {
            "connected": False,
            "error": f"{e}. Is TWS/Gateway running?",
        }

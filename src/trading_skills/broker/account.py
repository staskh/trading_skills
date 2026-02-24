# ABOUTME: Fetches account summary from Interactive Brokers.
# ABOUTME: Requires TWS or IB Gateway running locally.

import asyncio

from ib_async import IB


async def get_account_summary(port: int = 7496) -> dict:
    """Fetch account summary from IB."""
    ib = IB()

    try:
        await ib.connectAsync(host="127.0.0.1", port=port, clientId=2)
    except Exception as e:
        return {
            "connected": False,
            "error": f"Could not connect to IB on port {port}. Is TWS/Gateway running? Error: {e}",
        }

    try:
        accounts = ib.managedAccounts()
        if not accounts:
            return {"connected": True, "error": "No managed accounts found"}

        account_id = accounts[0]

        # Request account summary
        summary = ib.accountSummary(account_id)

        # Wait for data to populate
        await asyncio.sleep(1)
        summary = ib.accountSummary(account_id)

        # Convert to dict
        summary_dict = {}
        for item in summary:
            summary_dict[item.tag] = {
                "value": item.value,
                "currency": item.currency,
            }

        # Extract key values
        result = {
            "connected": True,
            "account": account_id,
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

        return result

    finally:
        ib.disconnect()

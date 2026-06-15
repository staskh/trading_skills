#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IB trade execution fetching.
# ABOUTME: Supports API, FlexReport web service, and local XML file sources.

import argparse
import asyncio
import json

from trading_skills.broker.trades import get_trades


async def main():
    parser = argparse.ArgumentParser(description="Fetch IB trade executions")
    parser.add_argument("--port", type=int, default=7497, help="IB port (7496=live, 7497=paper)")
    parser.add_argument("--account", type=str, default=None, help="Specific account ID to filter")
    parser.add_argument(
        "--all-accounts", action="store_true", help="Fetch trades for all managed accounts"
    )
    parser.add_argument("--symbol", type=str, default=None, help="Filter trades by symbol")
    parser.add_argument("--start-date", type=str, default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--flex-token", type=str, default=None, help="FlexReport token")
    parser.add_argument(
        "--flex-query-id",
        type=str,
        action="append",
        default=None,
        help="FlexReport query ID (repeat for multiple queries)",
    )
    parser.add_argument(
        "--file",
        type=str,
        action="append",
        default=None,
        help="Local FlexReport XML file (repeat for multiple files)",
    )

    args = parser.parse_args()
    result = await get_trades(
        port=args.port,
        account=args.account,
        all_accounts=args.all_accounts,
        symbol=args.symbol,
        start_date=args.start_date,
        end_date=args.end_date,
        flex_token=args.flex_token,
        flex_query_id=args.flex_query_id,
        files=args.file,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

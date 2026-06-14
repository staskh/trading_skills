#!/usr/bin/env python3
# ABOUTME: CLI wrapper for Questrade orders / executions.
import argparse
import json

from questrade_skills.trades import get_executions, get_orders


def main():
    p = argparse.ArgumentParser(description="Fetch Questrade orders/executions")
    p.add_argument("kind", choices=["orders", "executions"])
    p.add_argument("--account", default=None)
    p.add_argument("--all-accounts", action="store_true")
    p.add_argument("--start", default=None, help="ISO 8601 start time")
    p.add_argument("--end", default=None, help="ISO 8601 end time")
    p.add_argument("--state", default=None, help="orders only: All|Open|Closed")
    args = p.parse_args()

    if args.kind == "orders":
        result = get_orders(
            account=args.account, all_accounts=args.all_accounts,
            start_time=args.start, end_time=args.end, state_filter=args.state,
        )
    else:
        result = get_executions(
            account=args.account, all_accounts=args.all_accounts,
            start_time=args.start, end_time=args.end,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

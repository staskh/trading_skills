#!/usr/bin/env python3
# ABOUTME: CLI wrapper for Questrade portfolio positions.
import argparse
import json

from questrade_skills.portfolio import get_portfolio


def main():
    p = argparse.ArgumentParser(description="Fetch Questrade portfolio")
    p.add_argument("--account", default=None, help="Specific account number")
    p.add_argument("--all-accounts", action="store_true", help="All accounts")
    args = p.parse_args()
    result = get_portfolio(account=args.account, all_accounts=args.all_accounts)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

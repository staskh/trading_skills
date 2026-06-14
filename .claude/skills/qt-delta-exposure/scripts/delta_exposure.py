#!/usr/bin/env python3
# ABOUTME: CLI wrapper for Questrade delta-adjusted notional exposure.
import argparse
import json

from questrade_skills.delta_exposure import get_delta_exposure


def main():
    p = argparse.ArgumentParser(description="Questrade delta exposure")
    p.add_argument("--account", default=None)
    p.add_argument("--single", action="store_true", help="One account, not all")
    args = p.parse_args()
    result = get_delta_exposure(account=args.account, all_accounts=not args.single)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

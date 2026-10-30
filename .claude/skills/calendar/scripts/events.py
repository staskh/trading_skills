#!/usr/bin/env python3
# ABOUTME: CLI report of scheduled US economic events per weekday from the Nasdaq calendar.
# ABOUTME: Optionally cross-checks against ForexFactory's current week and fills Nasdaq's gaps.

import argparse
import json
import sys

from trading_skills.calendar_report import IMPACT_LEVELS, build_calendar_report


def main():
    parser = argparse.ArgumentParser(description="Report scheduled US economic events")
    parser.add_argument("--date", help="First day, YYYY-MM-DD (default: today ET)")
    parser.add_argument("--days", type=int, default=1, help="Number of weekdays (default: 1)")
    parser.add_argument(
        "--impact", choices=IMPACT_LEVELS, default="all", help="Events to list (default: all)"
    )
    parser.add_argument(
        "--forexfactory",
        action="store_true",
        help="Cross-check against ForexFactory (current week only)",
    )
    args = parser.parse_args()

    try:
        report = build_calendar_report(args.date, args.days, args.impact, args.forexfactory)
    except ValueError as exc:
        sys.exit(str(exc))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

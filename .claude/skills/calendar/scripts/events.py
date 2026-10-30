#!/usr/bin/env python3
# ABOUTME: CLI report of scheduled US economic events per weekday from the Nasdaq calendar.
# ABOUTME: Optionally cross-checks each day against ForexFactory's current-week calendar.

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from trading_skills.economic_calendar import fetch_us_economic_calendar
from trading_skills.forexfactory import compare_events, events_for_date, fetch_week
from trading_skills.utils import generated_at_str

NY = ZoneInfo("America/New_York")


def _weekdays(start: date, count: int) -> list[date]:
    """`count` weekdays from `start`; a weekend start rolls to the next Monday."""
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _forexfactory_day(week: list[dict] | None, date_str: str, nasdaq: list[dict] | None) -> dict:
    if week is None:
        return {"available": False, "note": "ForexFactory feed could not be fetched"}
    events = events_for_date(week, date_str)
    if events is None:
        return {"available": False, "note": "ForexFactory publishes only the current week"}
    return {
        "available": True,
        "events": events,
        "cross_check": compare_events(nasdaq or [], events),
    }


def build_report(start: date, count: int, impact: str, forexfactory: bool) -> dict:
    now = datetime.now(NY)
    week = fetch_week() if forexfactory else None
    days = []
    for day in _weekdays(start, count):
        date_str = day.isoformat()
        cal = fetch_us_economic_calendar(date_str, now=now)
        entry = {"date": date_str, "weekday": day.strftime("%a")}
        if cal is None:
            entry.update(
                verified=False,
                feed_date=None,
                events=None,
                note="Calendar unavailable or unverifiable — verify this day manually.",
            )
            all_events = None
        else:
            all_events = cal["events"]
            shown = [e for e in all_events if impact == "all" or e["impact"] == "high"]
            entry.update(verified=cal["verified"], feed_date=cal["feed_date"], events=shown)
        if forexfactory:
            entry["forexfactory"] = _forexfactory_day(week, date_str, all_events)
        days.append(entry)
    return {
        "generated_at": generated_at_str(),
        "data_delay": "real-time",
        "source": "nasdaq",
        "days": days,
    }


def main():
    parser = argparse.ArgumentParser(description="Report scheduled US economic events")
    parser.add_argument("--date", help="First day, YYYY-MM-DD (default: today ET)")
    parser.add_argument("--days", type=int, default=1, help="Number of weekdays (default: 1)")
    parser.add_argument(
        "--impact", choices=("all", "high"), default="all", help="Events to list (default: all)"
    )
    parser.add_argument(
        "--forexfactory",
        action="store_true",
        help="Cross-check against ForexFactory (current week only)",
    )
    args = parser.parse_args()

    if args.date:
        try:
            start = date.fromisoformat(args.date)
        except ValueError:
            sys.exit(f"--date must be YYYY-MM-DD, got {args.date!r}")
    else:
        start = datetime.now(NY).date()
    if args.days < 1:
        sys.exit("--days must be at least 1")

    print(json.dumps(build_report(start, args.days, args.impact, args.forexfactory), indent=2))


if __name__ == "__main__":
    main()

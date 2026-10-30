# ABOUTME: Builds the per-weekday US economic-events report shared by the calendar skill and MCP.
# ABOUTME: Nasdaq is the source; ForexFactory optionally cross-checks and fills its gaps.

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from trading_skills.economic_calendar import fetch_us_economic_calendar
from trading_skills.forexfactory import compare_events, events_for_date, fetch_week, fill_gaps
from trading_skills.utils import generated_at_str

NY = ZoneInfo("America/New_York")
IMPACT_LEVELS = ("all", "high")


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


def build_calendar_report(
    date_str: str | None = None,
    days: int = 1,
    impact: str = "all",
    forexfactory: bool = False,
) -> dict:
    """Scheduled US releases for `days` weekdays from date_str (YYYY-MM-DD, default today ET).

    Raises ValueError for a malformed date, days < 1, or an unknown impact level.
    """
    now = datetime.now(NY)
    if date_str:
        try:
            start = date.fromisoformat(date_str)
        except ValueError:
            raise ValueError(f"date must be YYYY-MM-DD, got {date_str!r}") from None
    else:
        start = now.date()
    if days < 1:
        raise ValueError(f"days must be at least 1, got {days}")
    if impact not in IMPACT_LEVELS:
        raise ValueError(f"impact must be one of {IMPACT_LEVELS}, got {impact!r}")

    week = fetch_week() if forexfactory else None
    report_days = []
    for day in _weekdays(start, days):
        day_str = day.isoformat()
        cal = fetch_us_economic_calendar(day_str, now=now)
        nasdaq = cal["events"] if cal else None
        entry = {
            "date": day_str,
            "weekday": day.strftime("%a"),
            "verified": cal["verified"] if cal else False,
            "feed_date": cal["feed_date"] if cal else None,
        }
        ff = _forexfactory_day(week, day_str, nasdaq) if forexfactory else None
        if ff and ff["available"]:
            events = fill_gaps(nasdaq, ff["events"])
            if nasdaq is None:
                entry["note"] = (
                    "Nasdaq calendar unavailable — events are ForexFactory's (no actuals)."
                )
        elif nasdaq is not None:
            events = [{**e, "source": "nasdaq"} for e in nasdaq]
        else:
            events = None
            entry["note"] = "Calendar unavailable or unverifiable — verify this day manually."
        if events is not None:
            events = [e for e in events if impact == "all" or e["impact"] == "high"]
        entry["events"] = events
        if ff:
            entry["forexfactory"] = ff
        report_days.append(entry)
    return {
        "generated_at": generated_at_str(),
        "data_delay": "real-time",
        "source": "nasdaq",
        "days": report_days,
    }

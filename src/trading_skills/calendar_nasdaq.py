# ABOUTME: Live US economic-event calendar via Nasdaq's public (keyless) endpoint.
# ABOUTME: Classifies market impact and returns a day's events in ET; degrades to None on failure.

from datetime import datetime, timedelta

import requests

# Nasdaq's economic-events feed. The "gmt" field is actually US Eastern time
# (e.g. Initial Jobless Claims shows 08:30, its canonical 8:30 AM ET release).
_NASDAQ_URL = "https://api.nasdaq.com/api/calendar/economicevents"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# The feed's `date` parameter is off by one: date=D returns D-1's releases
# (observed 2026-10-29: date=2026-10-29 served Wednesday's MBA/EIA/FOMC rows).
# Try D+1 first, then D, and accept whichever verifies against the target day.
_FEED_OFFSETS = (1, 0)

# Weekly releases with a fixed weekday (Mon=0) — used to verify which day a feed is.
_WEEKDAY_ANCHORS = {
    "redbook": 1,
    "api weekly crude": 1,
    "mba mortgage applications": 2,
    "crude oil inventories": 2,
    "initial jobless claims": 3,
    "continuing jobless claims": 3,
    "natural gas storage": 3,
    "fed's balance sheet": 3,
}

# Hardcoded FOMC announcement days (2nd day of each meeting, when the rate decision
# drops at 14:00 ET). The Nasdaq calendar feed unreliably omits these.
# Source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Update annually when the Fed publishes the next year's schedule (typically August).
# Dates marked (SEP) include the Summary of Economic Projections / dot plot.
_FOMC_ANNOUNCEMENT_DAYS: dict[int, list[str]] = {
    2025: [
        "2025-01-29",
        "2025-03-19",  # SEP
        "2025-05-07",
        "2025-06-18",  # SEP
        "2025-07-30",
        "2025-09-17",  # SEP
        "2025-10-29",
        "2025-12-10",  # SEP
    ],
    2026: [
        "2026-01-28",
        "2026-03-18",  # SEP
        "2026-04-29",
        "2026-06-17",  # SEP
        "2026-07-29",
        "2026-09-16",  # SEP ← confirmed
        "2026-10-28",
        "2026-12-09",  # SEP
    ],
}

# Event-name fragments that gap index level / spike vol — the ones a 0DTE cares about.
_HIGH_IMPACT = (
    "fomc",
    "federal funds",
    "interest rate decision",
    "cpi",
    "consumer price",
    "ppi",
    "producer price",
    "core pce",
    "pce price",
    "nonfarm",
    "non-farm",
    "payrolls",
    "unemployment rate",
    "gdp",
    "retail sales",
    "ism ",
)


def _clean(value) -> str | None:
    """Strip a Nasdaq cell to a value or None (it uses &nbsp; / blanks for empty)."""
    if not value:
        return None
    text = str(value).replace("&nbsp;", " ").strip()
    return text or None


def classify_impact(name: str) -> str:
    """Rate an event 'high' or 'medium' by market impact for index 0DTE."""
    n = name.lower()
    if "speaks" in n or "speech" in n:
        # Fed-chair remarks move markets; other officials are lower impact.
        return "high" if ("powell" in n or "chair" in n) else "medium"
    return "high" if any(k in n for k in _HIGH_IMPACT) else "medium"


def parse_events(rows: list[dict]) -> list[dict]:
    """Normalize raw Nasdaq rows into US events sorted high-impact first, then by time."""
    events = []
    for row in rows:
        if (row.get("country") or "").strip() != "United States":
            continue
        name = _clean(row.get("eventName"))
        if not name:
            continue
        time_et = None
        gmt = (row.get("gmt") or "").strip()  # actually ET, "HH:MM"
        if ":" in gmt:
            hh, _, mm = gmt.partition(":")
            if hh.isdigit() and mm.isdigit():
                time_et = f"{int(hh):02d}:{int(mm):02d} ET"
        events.append(
            {
                "event": name,
                "time_et": time_et,
                "impact": classify_impact(name),
                "actual": _clean(row.get("actual")),
                "consensus": _clean(row.get("consensus")),
                "previous": _clean(row.get("previous")),
            }
        )
    events.sort(key=lambda e: (e["impact"] != "high", e["time_et"] or "99:99"))
    return events


def is_fomc_day(date_str: str) -> bool:
    """Return True if date_str (YYYY-MM-DD) is an FOMC announcement day."""
    try:
        year = int(date_str[:4])
    except (ValueError, IndexError):
        return False
    return date_str in _FOMC_ANNOUNCEMENT_DAYS.get(year, [])


def _inject_fomc_if_missing(events: list[dict], date_str: str) -> list[dict]:
    """If date_str is an FOMC day and no FOMC event is already present, prepend one."""
    if not is_fomc_day(date_str):
        return events
    already_present = any(
        any(k in (e.get("event") or "").lower() for k in ("fomc", "federal funds", "interest rate"))
        for e in events
    )
    if already_present:
        return events
    fomc_event = {
        "event": "FOMC Rate Decision",
        "time_et": "14:00 ET",
        "impact": "high",
        "actual": None,
        "consensus": None,
        "previous": None,
        "source": "hardcoded",
    }
    return [fomc_event] + events


def _fetch_rows(feed_date: str, timeout: float) -> list[dict] | None:
    """Raw Nasdaq rows for the feed's `date` parameter, or None on failure."""
    try:
        resp = requests.get(
            _NASDAQ_URL, params={"date": feed_date}, headers=_HEADERS, timeout=timeout
        )
        if resp.status_code != 200:
            return None
        return ((resp.json() or {}).get("data") or {}).get("rows") or []
    except Exception:
        return None


def verify_events_date(events: list[dict], date_str: str, now: datetime | None = None) -> str:
    """Check that parsed events really belong to date_str (YYYY-MM-DD).

    Returns "verified", "rejected", or "unverifiable". Two independent checks:
    - weekday anchors: weekly releases (claims Thu, EIA/MBA Wed, Redbook Tue)
      must mostly land on date_str's weekday (majority vote tolerates holiday shifts);
    - when date_str is today: no event scheduled later than `now` may already
      carry an actual value — a printed future release means it's another day's data.
    """
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    match = mismatch = 0
    for e in events:
        name = (e.get("event") or "").lower()
        for fragment, weekday in _WEEKDAY_ANCHORS.items():
            if fragment in name:
                if weekday == target.weekday():
                    match += 1
                else:
                    mismatch += 1
                break
    if now is not None and now.date() == target:
        now_m = now.hour * 60 + now.minute
        for e in events:
            t = e.get("time_et")
            if t and e.get("actual") and e.get("source") != "hardcoded":
                hh, mm = int(t[:2]), int(t[3:5])
                if hh * 60 + mm > now_m + 5:
                    return "rejected"
    if mismatch > match:
        return "rejected"
    if match > mismatch:
        return "verified"
    return "unverifiable"


def fetch_us_economic_calendar(
    date_str: str, now: datetime | None = None, timeout: float = 10.0
) -> dict | None:
    """Return {events, verified, feed_date} for date_str (YYYY-MM-DD), or None.

    Nasdaq's `date` parameter is NOT the calendar day it returns: date=D has been
    observed to serve D-1's releases. So the label is never trusted — the D+1 and D
    feeds are both tried and the one whose contents verify as date_str wins. If
    neither verifies, a non-empty unverifiable (not contradicted) feed is used with
    verified=False; otherwise returns None (callers fall back to manual-verify
    guidance rather than show another day's events, or none, as today's).
    Always injects the FOMC Rate Decision on known announcement days.
    """
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    fallback = None
    for offset in _FEED_OFFSETS:
        feed_date = (target + timedelta(days=offset)).isoformat()
        rows = _fetch_rows(feed_date, timeout)
        if rows is None:
            continue
        events = parse_events(rows)
        status = verify_events_date(events, date_str, now)
        if status == "verified":
            return {
                "events": _inject_fomc_if_missing(events, date_str),
                "verified": True,
                "feed_date": feed_date,
            }
        # An empty unverified feed is no evidence of a quiet day — Nasdaq has
        # served empty pages for days that had releases.
        if status == "unverifiable" and events and fallback is None:
            fallback = {
                "events": _inject_fomc_if_missing(events, date_str),
                "verified": False,
                "feed_date": feed_date,
            }
    if fallback is not None:
        return fallback
    if is_fomc_day(date_str):
        return {
            "events": _inject_fomc_if_missing([], date_str),
            "verified": False,
            "feed_date": None,
        }
    return None


def fetch_us_economic_events(
    date_str: str, timeout: float = 10.0, now: datetime | None = None
) -> list[dict] | None:
    """Return a day's US economic events (times in ET), or None on any failure.

    Thin wrapper over fetch_us_economic_calendar that drops the verification metadata.
    Returns None (not []) so callers can distinguish "unavailable" from "no events".
    """
    cal = fetch_us_economic_calendar(date_str, now=now, timeout=timeout)
    return None if cal is None else cal["events"]

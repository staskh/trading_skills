# ABOUTME: Live US economic-event calendar via Nasdaq's public (keyless) endpoint.
# ABOUTME: Classifies market impact and returns a day's events in ET; degrades to None on failure.

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

NY = ZoneInfo("America/New_York")

# Nasdaq's economic-events feed. Its "gmt" column is neither GMT nor ET: it reads
# as a fixed UTC-4 clock, so it matches ET only on daylight-time dates (Initial
# Jobless Claims shows 08:30 in October, but standard-time 8:30 ET releases show
# 09:30). align_times converts it to ET.

# Fixed-offset clocks the feed may use: UTC-4 is observed; UTC-5 covers Nasdaq
# moving its clock to standard time. The first is the default.
_FEED_CLOCKS = (timezone(timedelta(hours=-4)), timezone(timedelta(hours=-5)))
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

# Releases whose ET time is fixed by the issuing agency; exact (lowercased) names.
# They measure the feed's clock offset on each day it is served.
_TIME_ANCHORS = {
    "initial jobless claims": "08:30",
    "continuing jobless claims": "08:30",
    "nonfarm payrolls": "08:30",
    "unemployment rate": "08:30",
    "cpi": "08:30",
    "core cpi": "08:30",
    "ppi": "08:30",
    "core ppi": "08:30",
    "retail sales": "08:30",
    "gdp": "08:30",
    "ism manufacturing pmi": "10:00",
    "ism non-manufacturing pmi": "10:00",
    "jolts job openings": "10:00",
    "michigan consumer sentiment": "10:00",
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


def _to_et(day: date, feed_time: str, clock: timezone) -> str:
    """Read a feed "HH:MM ET" as wall time on `clock` and convert it to America/New_York."""
    hh, mm = int(feed_time[:2]), int(feed_time[3:5])
    return datetime.combine(day, time(hh, mm), clock).astimezone(NY).strftime("%H:%M ET")


def _measure_clock(events: list[dict], day: date) -> timezone | None:
    """The feed clock that puts a clear majority of fixed-time releases at their ET time."""
    votes = Counter()
    for e in events:
        canonical = _TIME_ANCHORS.get(e["event"].strip().lower())
        if canonical and e.get("time_et"):
            for clock in _FEED_CLOCKS:
                if _to_et(day, e["time_et"], clock) == f"{canonical} ET":
                    votes[clock] += 1
    ranked = votes.most_common(2)
    if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
        return ranked[0][0]
    return None


def align_times(
    events: list[dict], date_str: str, reference: timezone | None = None
) -> tuple[list[dict], bool]:
    """Convert a day's feed times to ET. Returns (events, times_verified).

    The feed's clock is measured from the day's own fixed-time releases
    (_TIME_ANCHORS), else taken from `reference` (measured on another day in the
    same daylight/standard-time period); zoneinfo then converts it to ET for the
    date. With neither, the observed UTC-4 clock is used and times_verified=False.
    """
    day = date.fromisoformat(date_str)
    clock = _measure_clock(events, day) or reference
    verified = clock is not None
    clock = clock or _FEED_CLOCKS[0]
    aligned = [
        {**e, "time_et": _to_et(day, e["time_et"], clock)} if e.get("time_et") else e
        for e in events
    ]
    aligned.sort(key=lambda e: (e["impact"] != "high", e["time_et"] or "99:99"))
    return aligned, verified


def _is_standard_time(day: date) -> bool:
    return datetime.combine(day, time(12), NY).dst() == timedelta(0)


def _reference_clock(date_str: str, timeout: float) -> timezone | None:
    """Feed clock measured on the nearest Thursdays in date_str's daylight/standard period.

    The feed uses one clock for every date it serves, so the offset to ET depends only
    on whether a date falls in daylight or standard time. Thursdays carry Initial
    Jobless Claims (8:30 ET); up to three are tried, nearest first.
    """
    target = date.fromisoformat(date_str)
    thursday = target + timedelta(days=3 - target.weekday())
    candidates = [thursday + timedelta(weeks=k) for k in (0, -1, 1, -2, 2)]
    same_period = [d for d in candidates if _is_standard_time(d) == _is_standard_time(target)][:3]
    for day in same_period:
        for offset in _FEED_OFFSETS:
            rows = _fetch_rows((day + timedelta(days=offset)).isoformat(), timeout)
            clock = _measure_clock(parse_events(rows or []), day)
            if clock is not None:
                return clock
    return None


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
    """Return {events, verified, times_verified, feed_date} for date_str (YYYY-MM-DD), or None.

    Nasdaq's `date` parameter is NOT the calendar day it returns: date=D has been
    observed to serve D-1's releases. So the label is never trusted — the D+1 and D
    feeds are both tried and the one whose contents verify as date_str wins. If
    neither verifies, a non-empty unverifiable (not contradicted) feed is used with
    verified=False; otherwise returns None (callers fall back to manual-verify
    guidance rather than show another day's events, or none, as today's).
    Always injects the FOMC Rate Decision on known announcement days. Times are
    converted to ET by align_times; times_verified says whether the day held a
    fixed-time release to measure the feed's clock against.
    """
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    fallback = None
    reference: list[timezone | None] = []  # measured at most once, only when needed
    for offset in _FEED_OFFSETS:
        feed_date = (target + timedelta(days=offset)).isoformat()
        rows = _fetch_rows(feed_date, timeout)
        if rows is None:
            continue
        events = parse_events(rows)
        if _measure_clock(events, target) is None and not reference:
            reference.append(_reference_clock(date_str, timeout))
        events, times_verified = align_times(events, date_str, reference[0] if reference else None)
        status = verify_events_date(events, date_str, now)
        if status == "verified":
            return {
                "events": _inject_fomc_if_missing(events, date_str),
                "verified": True,
                "times_verified": times_verified,
                "feed_date": feed_date,
            }
        # An empty unverified feed is no evidence of a quiet day — Nasdaq has
        # served empty pages for days that had releases.
        if status == "unverifiable" and events and fallback is None:
            fallback = {
                "events": _inject_fomc_if_missing(events, date_str),
                "verified": False,
                "times_verified": times_verified,
                "feed_date": feed_date,
            }
    if fallback is not None:
        return fallback
    if is_fomc_day(date_str):
        return {
            "events": _inject_fomc_if_missing([], date_str),
            "verified": False,
            "times_verified": True,  # only the hardcoded 14:00 ET decision
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

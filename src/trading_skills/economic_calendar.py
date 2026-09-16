# ABOUTME: Live US economic-event calendar via Nasdaq's public (keyless) endpoint.
# ABOUTME: Classifies market impact and returns a day's events in ET; degrades to None on failure.

import requests

# Nasdaq's economic-events feed. The "gmt" field is actually US Eastern time
# (e.g. Initial Jobless Claims shows 08:30, its canonical 8:30 AM ET release).
_NASDAQ_URL = "https://api.nasdaq.com/api/calendar/economicevents"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

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


def fetch_us_economic_events(date_str: str, timeout: float = 10.0) -> list[dict] | None:
    """Return a day's US economic events (times in ET), or None on any failure.

    date_str: YYYY-MM-DD. Uses Nasdaq's public economic-events endpoint (no key).
    Always injects the FOMC Rate Decision on known announcement days regardless of
    whether the live feed includes it — the Nasdaq calendar unreliably omits FOMC.
    Returns None (not []) so callers can distinguish "unavailable" from "no events".
    """
    try:
        resp = requests.get(
            _NASDAQ_URL, params={"date": date_str}, headers=_HEADERS, timeout=timeout
        )
        if resp.status_code != 200:
            # Even on fetch failure, return FOMC if today is a meeting day.
            if is_fomc_day(date_str):
                return _inject_fomc_if_missing([], date_str)
            return None
        rows = ((resp.json() or {}).get("data") or {}).get("rows") or []
    except Exception:
        if is_fomc_day(date_str):
            return _inject_fomc_if_missing([], date_str)
        return None
    return _inject_fomc_if_missing(parse_events(rows), date_str)

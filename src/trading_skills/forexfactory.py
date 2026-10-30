# ABOUTME: ForexFactory's weekly economic calendar (keyless JSON mirror) as a reference source.
# ABOUTME: Normalizes its US events to ET and cross-checks them against the Nasdaq calendar.

import json
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

NY = ZoneInfo("America/New_York")

# Publishes the current Sun-Sat week only: no history, no later weeks, no actual values.
_WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# The feed answers HTTP 429 (retry-after 300s) to more than about one request per
# five minutes, so the week is cached locally and reused for an hour.
_CACHE_PATH = Path(tempfile.gettempdir()) / "trading_skills_forexfactory_week.json"
_CACHE_TTL_S = 3600

# Reference impact levels worth checking against the primary calendar.
_CHECKED_IMPACT = ("high", "medium")

# Spellings that differ between the two feeds for the same release.
_ALIASES = (
    ("non-farm", "nonfarm"),
    ("federal funds rate", "fomc"),
    ("interest rate decision", "fomc"),
)

# Words too generic to identify a release on their own (e.g. Chicago PMI vs S&P PMI).
_GENERIC = {
    "advance",
    "prelim",
    "final",
    "index",
    "rate",
    "change",
    "price",
    "prices",
    "pmi",
    "us",
    "the",
    "of",
}


def _read_cache(path: Path) -> list[dict] | None:
    try:
        rows = json.loads(path.read_text())
        return rows if isinstance(rows, list) else None
    except Exception:
        return None


def fetch_week(timeout: float = 10.0, cache_path: Path = _CACHE_PATH) -> list[dict] | None:
    """Raw rows for the current week, or None on any failure.

    Serves the local copy when it is under an hour old. When a fetch fails, an
    older copy is used instead; events_for_date rejects days outside its week.
    """
    try:
        if time.time() - cache_path.stat().st_mtime < _CACHE_TTL_S:
            cached = _read_cache(cache_path)
            if cached is not None:
                return cached
    except OSError:
        pass
    try:
        resp = requests.get(_WEEK_URL, headers=_HEADERS, timeout=timeout)
        rows = resp.json() if resp.status_code == 200 else None
    except Exception:
        rows = None
    if not isinstance(rows, list):
        return _read_cache(cache_path)
    try:
        cache_path.write_text(json.dumps(rows))
    except OSError:
        pass
    return rows


def _clean(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _et(row: dict) -> datetime:
    return datetime.fromisoformat(row["date"]).astimezone(NY)


def events_for_date(rows: list[dict], date_str: str) -> list[dict] | None:
    """US events on date_str (YYYY-MM-DD, ET) sorted by time, or None if outside the feed's week."""
    days = {_et(r).date().isoformat() for r in rows}
    if not days or not (min(days) <= date_str <= max(days)):
        return None
    events = []
    for row in rows:
        if row.get("country") != "USD":
            continue
        when = _et(row)
        if when.date().isoformat() != date_str:
            continue
        events.append(
            {
                "event": row.get("title"),
                "time_et": when.strftime("%H:%M ET"),
                "impact": (row.get("impact") or "").lower(),
                "consensus": _clean(row.get("forecast")),
                "previous": _clean(row.get("previous")),
            }
        )
    return sorted(events, key=lambda e: e["time_et"])


def _words(name: str) -> set[str]:
    text = name.lower()
    for spelling, canonical in _ALIASES:
        text = text.replace(spelling, canonical)
    return {w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 1}


def _keywords(name: str) -> set[str]:
    return _words(name) - _GENERIC


def _closeness(a: str, b: str) -> tuple[int, int]:
    """Shared keywords first, then shared words of any kind to break ties."""
    return len(_keywords(a) & _keywords(b)), len(_words(a) & _words(b))


def compare_events(nasdaq: list[dict], reference: list[dict]) -> dict:
    """Cross-check a day's Nasdaq events against the reference (ForexFactory) events.

    Each high/medium reference event is confirmed (same release at the same time),
    a time_mismatch (same release at another time), or missing_in_nasdaq. High-impact
    Nasdaq events that share no keyword with any reference event are nasdaq_only.
    """
    result = {"confirmed": [], "time_mismatch": [], "missing_in_nasdaq": [], "nasdaq_only": []}
    for ref in reference:
        if ref.get("impact") not in _CHECKED_IMPACT:
            continue
        words = _keywords(ref["event"])
        same_release = [n for n in nasdaq if words & _keywords(n["event"])]
        same_time = [n for n in same_release if n.get("time_et") == ref["time_et"]]
        if same_time:
            best = max(same_time, key=lambda n: _closeness(ref["event"], n["event"]))
            result["confirmed"].append(
                {"event": ref["event"], "time_et": ref["time_et"], "nasdaq_event": best["event"]}
            )
        elif same_release:
            best = max(same_release, key=lambda n: _closeness(ref["event"], n["event"]))
            result["time_mismatch"].append(
                {
                    "event": ref["event"],
                    "time_et": ref["time_et"],
                    "nasdaq_event": best["event"],
                    "nasdaq_time_et": best.get("time_et"),
                }
            )
        else:
            result["missing_in_nasdaq"].append(
                {"event": ref["event"], "time_et": ref["time_et"], "impact": ref["impact"]}
            )
    reference_words = [_keywords(r["event"]) for r in reference]
    for n in nasdaq:
        if n.get("impact") != "high":
            continue
        if not any(_keywords(n["event"]) & words for words in reference_words):
            result["nasdaq_only"].append({"event": n["event"], "time_et": n.get("time_et")})
    return result

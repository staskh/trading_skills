# ABOUTME: End-to-end tests for the calendar skill script against the live feeds.
# ABOUTME: Checks report shape, weekday stepping, impact filter and the ForexFactory cross-check.

import json
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SCRIPT_PATH = Path(__file__).parent.parent / ".claude/skills/calendar/scripts/events.py"
NY = ZoneInfo("America/New_York")


def run_events(*args) -> dict:
    """Run events.py and return parsed JSON output."""
    cmd = ["uv", "run", "python", str(SCRIPT_PATH)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Script failed: {result.stderr}")
    return json.loads(result.stdout)


def _this_week_weekday() -> str:
    """A weekday in the current Sun-Sat week, the only week ForexFactory publishes."""
    today = datetime.now(NY).date()
    day = today if today.weekday() < 5 else today - timedelta(days=today.weekday() - 4)
    return day.isoformat()


class TestReport:
    def test_has_required_metadata(self):
        result = run_events("--date", "2026-10-29")
        assert result["generated_at"].endswith(" ET")
        assert result["data_delay"] == "real-time"
        assert result["source"] == "nasdaq"

    def test_steps_over_weekends(self):
        result = run_events("--date", "2026-10-30", "--days", "2")
        assert [d["date"] for d in result["days"]] == ["2026-10-30", "2026-11-02"]
        assert [d["weekday"] for d in result["days"]] == ["Fri", "Mon"]

    def test_day_reports_events_or_unavailable(self):
        day = run_events("--date", "2026-10-29")["days"][0]
        assert "verified" in day
        if day["events"] is None:
            assert "manually" in day["note"]
        else:
            assert all({"event", "time_et", "impact"} <= set(e) for e in day["events"])

    def test_high_impact_filter(self):
        day = run_events("--date", "2026-10-29", "--impact", "high")["days"][0]
        assert all(e["impact"] == "high" for e in day["events"] or [])

    def test_no_forexfactory_section_without_the_flag(self):
        day = run_events("--date", "2026-10-29")["days"][0]
        assert "forexfactory" not in day

    def test_rejects_malformed_date(self):
        with pytest.raises(RuntimeError, match="YYYY-MM-DD"):
            run_events("--date", "10/29/2026")


class TestForexFactoryCrossCheck:
    def test_current_week_day_is_cross_checked(self):
        day = run_events("--date", _this_week_weekday(), "--forexfactory")["days"][0]
        ff = day["forexfactory"]
        if not ff["available"]:
            pytest.skip(f"ForexFactory feed unavailable: {ff['note']}")
        assert isinstance(ff["events"], list)
        assert set(ff["cross_check"]) == {
            "confirmed",
            "time_mismatch",
            "missing_in_nasdaq",
            "nasdaq_only",
        }

    def test_gaps_are_filled_and_every_event_names_its_source(self):
        day = run_events("--date", _this_week_weekday(), "--forexfactory")["days"][0]
        if not day["forexfactory"]["available"]:
            pytest.skip(f"ForexFactory feed unavailable: {day['forexfactory']['note']}")
        assert day["events"] is not None
        assert {e["source"] for e in day["events"]} <= {"nasdaq", "forexfactory"}
        added = {e["event"] for e in day["events"] if e["source"] == "forexfactory"}
        missing = {m["event"] for m in day["forexfactory"]["cross_check"]["missing_in_nasdaq"]}
        assert missing <= added

    def test_day_outside_the_published_week_is_unavailable(self):
        day = run_events("--date", date(2026, 1, 5).isoformat(), "--forexfactory")["days"][0]
        assert day["forexfactory"]["available"] is False
        assert "week" in day["forexfactory"]["note"]

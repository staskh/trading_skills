# ABOUTME: Tests for the ForexFactory weekly calendar reader and the source cross-check.
# ABOUTME: Runs offline on rows captured from the live feed for the week of 2026-10-25.

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

from trading_skills.calendar_forexfactory import (
    compare_events,
    events_for_date,
    fetch_week,
    fill_gaps,
)

# Rows as served by nfs.faireconomy.media/ff_calendar_thisweek.json (week of 2026-10-25).
_WEEK = [
    {
        "title": "ADP Weekly Employment Change",
        "country": "USD",
        "date": "2026-10-25T20:15:00-04:00",
        "impact": "Low",
        "forecast": "",
        "previous": "18.5K",
    },
    {
        "title": "Advance GDP q/q",
        "country": "USD",
        "date": "2026-10-29T08:30:00-04:00",
        "impact": "High",
        "forecast": "3.2%",
        "previous": "1.5%",
    },
    {
        "title": "Unemployment Claims",
        "country": "USD",
        "date": "2026-10-29T08:30:00-04:00",
        "impact": "Medium",
        "forecast": "198K",
        "previous": "194K",
    },
    {
        "title": "Natural Gas Storage",
        "country": "USD",
        "date": "2026-10-29T10:30:00-04:00",
        "impact": "Low",
        "forecast": "75B",
        "previous": "77B",
    },
    {
        "title": "German Prelim CPI m/m",
        "country": "EUR",
        "date": "2026-10-29T08:00:00-04:00",
        "impact": "High",
        "forecast": "0.2%",
        "previous": "0.2%",
    },
    {
        "title": "Employment Cost Index q/q",
        "country": "USD",
        "date": "2026-10-30T08:30:00-04:00",
        "impact": "Medium",
        "forecast": "0.8%",
        "previous": "0.9%",
    },
    {
        "title": "Non-Farm Employment Change",
        "country": "USD",
        "date": "2026-10-31T01:30:00+00:00",
        "impact": "High",
        "forecast": "",
        "previous": "",
    },
]


def _nasdaq(name, time_et, impact="medium"):
    return {"event": name, "time_et": time_et, "impact": impact}


class TestEventsForDate:
    def test_keeps_only_us_events_on_the_day(self):
        events = events_for_date(_WEEK, "2026-10-29")
        assert [e["event"] for e in events] == [
            "Advance GDP q/q",
            "Unemployment Claims",
            "Natural Gas Storage",
        ]

    def test_times_and_values_are_normalized(self):
        gdp = events_for_date(_WEEK, "2026-10-29")[0]
        assert gdp == {
            "event": "Advance GDP q/q",
            "time_et": "08:30 ET",
            "impact": "high",
            "consensus": "3.2%",
            "previous": "1.5%",
        }

    def test_day_is_taken_in_eastern_time(self):
        # 01:30 UTC on Oct 31 is 21:30 ET on Oct 30.
        names = [e["event"] for e in events_for_date(_WEEK, "2026-10-30")]
        assert "Non-Farm Employment Change" in names
        assert events_for_date(_WEEK, "2026-10-30")[-1]["time_et"] == "21:30 ET"

    def test_winter_offset_converts_to_eastern(self):
        row = {**_WEEK[1], "date": "2026-11-06T13:30:00+00:00"}
        assert events_for_date([row], "2026-11-06")[0]["time_et"] == "08:30 ET"

    def test_blank_values_become_none(self):
        nfp = events_for_date(_WEEK, "2026-10-30")[-1]
        assert nfp["consensus"] is None
        assert nfp["previous"] is None

    def test_day_outside_the_published_week_is_none(self):
        assert events_for_date(_WEEK, "2026-11-05") is None

    def test_day_inside_the_week_without_us_events_is_empty(self):
        assert events_for_date(_WEEK, "2026-10-27") == []


class TestCompareEvents:
    def _ff(self):
        return events_for_date(_WEEK, "2026-10-29")

    def test_same_release_at_the_same_time_is_confirmed(self):
        nasdaq = [_nasdaq("GDP", "08:30 ET", "high"), _nasdaq("Initial Jobless Claims", "08:30 ET")]
        result = compare_events(nasdaq, self._ff())
        assert [c["event"] for c in result["confirmed"]] == [
            "Advance GDP q/q",
            "Unemployment Claims",
        ]
        assert result["confirmed"][0]["nasdaq_event"] == "GDP"
        assert result["time_mismatch"] == []
        assert result["missing_in_nasdaq"] == []

    def test_same_release_an_hour_off_is_a_time_mismatch(self):
        nasdaq = [_nasdaq("GDP", "09:30 ET", "high"), _nasdaq("Initial Jobless Claims", "08:30 ET")]
        result = compare_events(nasdaq, self._ff())
        assert result["time_mismatch"] == [
            {
                "event": "Advance GDP q/q",
                "time_et": "08:30 ET",
                "nasdaq_event": "GDP",
                "nasdaq_time_et": "09:30 ET",
            }
        ]

    def test_release_nasdaq_lacks_is_missing(self):
        nasdaq = [_nasdaq("Initial Jobless Claims", "08:30 ET")]
        result = compare_events(nasdaq, self._ff())
        assert result["missing_in_nasdaq"] == [
            {"event": "Advance GDP q/q", "time_et": "08:30 ET", "impact": "high"}
        ]

    def test_low_impact_reference_events_are_not_checked(self):
        result = compare_events([], self._ff())
        assert "Natural Gas Storage" not in [m["event"] for m in result["missing_in_nasdaq"]]

    def test_high_impact_nasdaq_release_absent_from_reference_is_reported(self):
        nasdaq = [
            _nasdaq("GDP", "08:30 ET", "high"),
            _nasdaq("Initial Jobless Claims", "08:30 ET"),
            _nasdaq("Retail Sales", "08:30 ET", "high"),
        ]
        result = compare_events(nasdaq, self._ff())
        assert result["nasdaq_only"] == [{"event": "Retail Sales", "time_et": "08:30 ET"}]

    def test_hyphenated_and_plain_names_match(self):
        ff = events_for_date(_WEEK, "2026-10-30")
        nasdaq = [
            _nasdaq("Nonfarm Payrolls", "21:30 ET", "high"),
            _nasdaq("Employment Cost Index", "08:30 ET"),
        ]
        result = compare_events(nasdaq, ff)
        assert {c["event"] for c in result["confirmed"]} == {
            "Non-Farm Employment Change",
            "Employment Cost Index q/q",
        }

    def test_generic_words_alone_do_not_match(self):
        ff = [{"event": "Chicago PMI", "time_et": "09:45 ET", "impact": "high"}]
        nasdaq = [_nasdaq("S&P Global Manufacturing PMI", "09:45 ET")]
        result = compare_events(nasdaq, ff)
        assert result["confirmed"] == []
        assert [m["event"] for m in result["missing_in_nasdaq"]] == ["Chicago PMI"]

    def test_closest_name_wins_among_same_time_candidates(self):
        ff = [{"event": "Advance GDP Price Index q/q", "time_et": "08:30 ET", "impact": "medium"}]
        nasdaq = [
            _nasdaq("GDP", "08:30 ET", "high"),
            _nasdaq("GDP Price Index", "08:30 ET", "high"),
        ]
        result = compare_events(nasdaq, ff)
        assert result["confirmed"][0]["nasdaq_event"] == "GDP Price Index"

    def test_fed_rate_decision_names_match(self):
        ff = [{"event": "Federal Funds Rate", "time_et": "14:00 ET", "impact": "high"}]
        nasdaq = [_nasdaq("FOMC Rate Decision", "14:00 ET", "high")]
        result = compare_events(nasdaq, ff)
        assert [c["nasdaq_event"] for c in result["confirmed"]] == ["FOMC Rate Decision"]


class _Feed:
    """Stands in for the HTTP endpoint: serves `status` and counts requests."""

    def __init__(self, status=200, rows=_WEEK):
        self.status, self.rows, self.calls = status, rows, 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return SimpleNamespace(status_code=self.status, json=lambda: self.rows)


class TestFetchWeekCache:
    def test_second_fetch_within_the_hour_reuses_the_cache(self, tmp_path):
        feed, cache = _Feed(), tmp_path / "week.json"
        with patch("trading_skills.calendar_forexfactory.requests.get", feed.get):
            assert fetch_week(cache_path=cache) == _WEEK
            assert fetch_week(cache_path=cache) == _WEEK
        assert feed.calls == 1

    def test_stale_cache_is_refreshed(self, tmp_path):
        feed, cache = _Feed(), tmp_path / "week.json"
        cache.write_text(json.dumps(_WEEK[:1]))
        two_hours_ago = time.time() - 7200
        os.utime(cache, (two_hours_ago, two_hours_ago))
        with patch("trading_skills.calendar_forexfactory.requests.get", feed.get):
            assert fetch_week(cache_path=cache) == _WEEK
        assert feed.calls == 1

    def test_rate_limited_fetch_falls_back_to_stale_cache(self, tmp_path):
        feed, cache = _Feed(status=429), tmp_path / "week.json"
        cache.write_text(json.dumps(_WEEK))
        two_hours_ago = time.time() - 7200
        os.utime(cache, (two_hours_ago, two_hours_ago))
        with patch("trading_skills.calendar_forexfactory.requests.get", feed.get):
            assert fetch_week(cache_path=cache) == _WEEK

    def test_rate_limited_fetch_without_cache_is_none(self, tmp_path):
        with patch("trading_skills.calendar_forexfactory.requests.get", _Feed(status=429).get):
            assert fetch_week(cache_path=tmp_path / "week.json") is None


class TestFillGaps:
    def test_adds_reference_releases_nasdaq_lacks(self):
        nasdaq = [_nasdaq("Initial Jobless Claims", "08:30 ET")]
        merged = fill_gaps(nasdaq, events_for_date(_WEEK, "2026-10-29"))
        added = [e for e in merged if e["source"] == "forexfactory"]
        assert added == [
            {
                "event": "Advance GDP q/q",
                "time_et": "08:30 ET",
                "impact": "high",
                "actual": None,
                "consensus": "3.2%",
                "previous": "1.5%",
                "source": "forexfactory",
            }
        ]

    def test_nasdaq_events_are_kept_and_tagged(self):
        nasdaq = [_nasdaq("Initial Jobless Claims", "08:30 ET")]
        merged = fill_gaps(nasdaq, events_for_date(_WEEK, "2026-10-29"))
        kept = [e for e in merged if e["source"] == "nasdaq"]
        assert kept == [{**nasdaq[0], "source": "nasdaq"}]

    def test_low_impact_reference_releases_are_not_added(self):
        merged = fill_gaps([], events_for_date(_WEEK, "2026-10-29"))
        assert "Natural Gas Storage" not in [e["event"] for e in merged]

    def test_without_nasdaq_the_whole_reference_day_is_used(self):
        merged = fill_gaps(None, events_for_date(_WEEK, "2026-10-29"))
        assert [e["event"] for e in merged] == [
            "Advance GDP q/q",
            "Unemployment Claims",
            "Natural Gas Storage",
        ]
        assert {e["source"] for e in merged} == {"forexfactory"}

    def test_high_impact_first_then_by_time(self):
        nasdaq = [
            _nasdaq("Natural Gas Storage", "10:30 ET"),
            _nasdaq("Initial Jobless Claims", "08:30 ET"),
        ]
        merged = fill_gaps(nasdaq, events_for_date(_WEEK, "2026-10-29"))
        assert [e["event"] for e in merged] == [
            "Advance GDP q/q",
            "Initial Jobless Claims",
            "Natural Gas Storage",
        ]

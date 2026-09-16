# ABOUTME: Tests for the live US economic-calendar module.
# ABOUTME: Parsing/classification run offline; the live Nasdaq fetch is marked manual.

import pytest

from trading_skills.economic_calendar import (
    _inject_fomc_if_missing,
    classify_impact,
    fetch_us_economic_events,
    is_fomc_day,
    parse_events,
)


class TestClassifyImpact:
    def test_major_releases_are_high(self):
        for name in [
            "FOMC Statement",
            "Fed Interest Rate Decision",
            "CPI (YoY)",
            "Core PCE Price Index",
            "Nonfarm Payrolls",
            "GDP (QoQ)",
            "Retail Sales (MoM)",
            "ISM Manufacturing PMI",
        ]:
            assert classify_impact(name) == "high", name

    def test_fed_chair_speech_is_high_others_medium(self):
        assert classify_impact("Fed Chair Powell Speaks") == "high"
        assert classify_impact("FOMC Member Williams Speaks") == "medium"

    def test_routine_events_are_medium(self):
        assert classify_impact("Existing Home Sales") == "medium"
        assert classify_impact("4-Week Bill Auction") == "medium"


class TestParseEvents:
    def _rows(self):
        return [
            {"country": "Germany", "eventName": "German Exports", "gmt": "02:00"},
            {
                "country": "United States",
                "eventName": "Initial Jobless Claims",
                "gmt": "08:30",
                "actual": "215K",
                "consensus": "218K",
                "previous": "&nbsp;",
            },
            {
                "country": "United States",
                "eventName": "FOMC Statement",
                "gmt": "14:00",
                "actual": "",
                "consensus": " ",
            },
            {"country": "United States", "eventName": "", "gmt": "10:00"},  # dropped: no name
        ]

    def test_filters_to_us_and_drops_nameless(self):
        events = parse_events(self._rows())
        names = [e["event"] for e in events]
        assert "German Exports" not in names
        assert set(names) == {"Initial Jobless Claims", "FOMC Statement"}

    def test_high_impact_sorts_first(self):
        events = parse_events(self._rows())
        assert events[0]["event"] == "FOMC Statement"  # high beats medium
        assert events[0]["impact"] == "high"

    def test_time_parsed_as_et_and_cells_cleaned(self):
        events = parse_events(self._rows())
        claims = next(e for e in events if e["event"] == "Initial Jobless Claims")
        assert claims["time_et"] == "08:30 ET"
        assert claims["actual"] == "215K"
        assert claims["previous"] is None  # &nbsp; cleaned to None
        fomc = next(e for e in events if e["event"] == "FOMC Statement")
        assert fomc["consensus"] is None  # blank cleaned to None


class TestFomcDay:
    def test_known_announcement_days_are_fomc(self):
        # Sep 16 2026 is confirmed (search-verified)
        assert is_fomc_day("2026-09-16") is True
        assert is_fomc_day("2026-01-28") is True
        assert is_fomc_day("2025-12-10") is True

    def test_non_fomc_days_are_not(self):
        assert is_fomc_day("2026-09-17") is False  # day after
        assert is_fomc_day("2026-09-15") is False  # day before (1st day of meeting)
        assert is_fomc_day("2026-06-01") is False

    def test_unknown_year_returns_false(self):
        assert is_fomc_day("2030-01-01") is False

    def test_malformed_date_returns_false(self):
        assert is_fomc_day("bad") is False
        assert is_fomc_day("") is False


class TestInjectFomc:
    def test_injects_on_fomc_day_when_absent(self):
        events = _inject_fomc_if_missing([], "2026-09-16")
        assert len(events) == 1
        assert events[0]["event"] == "FOMC Rate Decision"
        assert events[0]["time_et"] == "14:00 ET"
        assert events[0]["impact"] == "high"
        assert events[0]["source"] == "hardcoded"

    def test_prepends_before_other_events(self):
        other = [{"event": "Retail Sales", "time_et": "08:30 ET", "impact": "high"}]
        events = _inject_fomc_if_missing(other, "2026-09-16")
        assert events[0]["event"] == "FOMC Rate Decision"
        assert events[1]["event"] == "Retail Sales"

    def test_no_inject_on_non_fomc_day(self):
        events = _inject_fomc_if_missing([], "2026-09-17")
        assert events == []

    def test_no_duplicate_if_already_present(self):
        existing = [{"event": "FOMC Statement", "time_et": "14:00 ET", "impact": "high"}]
        events = _inject_fomc_if_missing(existing, "2026-09-16")
        fomc_events = [
            e for e in events if "fomc" in e["event"].lower() or "rate" in e["event"].lower()
        ]
        assert len(fomc_events) == 1

    def test_no_duplicate_interest_rate_decision_variant(self):
        existing = [
            {"event": "Fed Interest Rate Decision", "time_et": "14:00 ET", "impact": "high"}
        ]  # noqa: E501
        events = _inject_fomc_if_missing(existing, "2026-09-16")
        assert len(events) == 1  # not injected, already there


@pytest.mark.manual
class TestLiveFetch:
    def test_fetch_returns_list_or_none(self):
        # Live Nasdaq endpoint; a weekday should return some US events.
        result = fetch_us_economic_events("2026-07-10")
        assert result is None or isinstance(result, list)

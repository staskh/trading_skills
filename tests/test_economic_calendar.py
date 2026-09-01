# ABOUTME: Tests for the live US economic-calendar module.
# ABOUTME: Parsing/classification run offline; the live Nasdaq fetch is marked manual.

import pytest

from trading_skills.economic_calendar import (
    classify_impact,
    fetch_us_economic_events,
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


@pytest.mark.manual
class TestLiveFetch:
    def test_fetch_returns_list_or_none(self):
        # Live Nasdaq endpoint; a weekday should return some US events.
        result = fetch_us_economic_events("2026-07-10")
        assert result is None or isinstance(result, list)

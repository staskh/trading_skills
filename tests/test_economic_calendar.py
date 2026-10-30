# ABOUTME: Tests for the live US economic-calendar module.
# ABOUTME: Parsing/classification run offline; the live Nasdaq fetch is marked manual.

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from trading_skills.calendar_nasdaq import (
    _inject_fomc_if_missing,
    align_times,
    classify_impact,
    fetch_us_economic_calendar,
    fetch_us_economic_events,
    is_fomc_day,
    parse_events,
    verify_events_date,
)

NY = ZoneInfo("America/New_York")


def _row(gmt, name, actual=""):
    return {"country": "United States", "gmt": gmt, "eventName": name, "actual": actual}


# Real Nasdaq responses observed 2026-10-29 (Thu): the `date` label is one day ahead
# of the contents — date=2026-10-29 served Wednesday's rows, date=2026-10-30 Thursday's.
_FEED = {
    "2026-10-29": [  # actually Wed Oct 28
        _row("07:00", "MBA Mortgage Applications", "3.4%"),
        _row("10:30", "Crude Oil Inventories", "-1.892M"),
        _row("14:00", "FOMC Statement", "&nbsp;"),
        _row("14:00", "Fed Interest Rate Decision", "4.00%"),
    ],
    "2026-10-30": [  # actually Thu Oct 29
        _row("08:30", "Initial Jobless Claims", "194K"),
        _row("08:30", "Continuing Jobless Claims", "1,701K"),
        _row("08:30", "GDP", "3.4%"),
        _row("10:30", "Natural Gas Storage", "&nbsp;"),
        _row("13:00", "7-Year Note Auction", "&nbsp;"),
    ],
}


def _fake_rows(feed_date, timeout):
    return _FEED.get(feed_date)


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


class TestVerifyEventsDate:
    def test_wednesday_rows_rejected_for_thursday(self):
        events = parse_events(_FEED["2026-10-29"])
        assert verify_events_date(events, "2026-10-29") == "rejected"

    def test_thursday_rows_verified_for_thursday(self):
        events = parse_events(_FEED["2026-10-30"])
        assert verify_events_date(events, "2026-10-29") == "verified"

    def test_future_release_with_actual_rejected_today(self):
        # A 14:00 release already printed at 09:42 can't be today's data.
        events = parse_events([_row("14:00", "Some Survey", "51.0")])
        now = datetime(2026, 10, 29, 9, 42, tzinfo=NY)
        assert verify_events_date(events, "2026-10-29", now) == "rejected"

    def test_no_anchors_is_unverifiable(self):
        events = parse_events([_row("10:00", "Consumer Sentiment", "")])
        assert verify_events_date(events, "2026-10-26") == "unverifiable"

    def test_holiday_shift_majority_still_verifies(self):
        # Thanksgiving week: claims move to Wednesday, MBA/EIA stay — 2 vs 1.
        events = parse_events(
            [
                _row("07:00", "MBA Mortgage Applications", "1%"),
                _row("08:30", "Initial Jobless Claims", "200K"),
                _row("10:30", "Crude Oil Inventories", "1M"),
            ]
        )
        assert verify_events_date(events, "2026-11-25") == "verified"


class TestFetchCalendarOffset:
    @patch("trading_skills.calendar_nasdaq._fetch_rows", side_effect=_fake_rows)
    def test_returns_the_true_day_not_the_label(self, _):
        now = datetime(2026, 10, 29, 9, 42, tzinfo=NY)
        cal = fetch_us_economic_calendar("2026-10-29", now=now)
        names = [e["event"] for e in cal["events"]]
        assert cal["verified"] is True
        assert cal["feed_date"] == "2026-10-30"
        assert "Initial Jobless Claims" in names
        assert "FOMC Statement" not in names
        assert "MBA Mortgage Applications" not in names

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_falls_back_to_unshifted_feed_if_offset_disappears(self, mock_rows):
        # If Nasdaq fixes the label, date=D holds D's rows and D+1 holds Friday's.
        mock_rows.side_effect = lambda d, t: {
            "2026-10-30": [_row("08:30", "Nonfarm Payrolls", "")],
            "2026-10-29": _FEED["2026-10-30"],
        }.get(d)
        cal = fetch_us_economic_calendar("2026-10-29")
        assert cal["verified"] is True
        assert cal["feed_date"] == "2026-10-29"

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_contradicting_feeds_return_none(self, mock_rows):
        mock_rows.return_value = _FEED["2026-10-29"]  # Wednesday rows everywhere
        assert fetch_us_economic_calendar("2026-10-29") is None

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_empty_unverified_feed_is_unavailable_not_event_free(self, mock_rows):
        # Observed for Thu 2026-11-05: date=11-06 came back empty and date=11-05
        # held Wednesday's rows. An empty unverified feed is no evidence of a quiet day.
        mock_rows.side_effect = lambda d, t: {
            "2026-10-30": [],
            "2026-10-29": _FEED["2026-10-29"],
        }.get(d)
        assert fetch_us_economic_calendar("2026-10-29") is None

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_empty_unverified_feed_on_fomc_day_flags_only_fomc(self, mock_rows):
        # Observed for Wed 2026-10-28: date=10-29 empty, date=10-28 held Tuesday's rows.
        mock_rows.side_effect = lambda d, t: {
            "2026-10-29": [],
            "2026-10-28": [_row("08:55", "Redbook", "6.1%")],
        }.get(d)
        cal = fetch_us_economic_calendar("2026-10-28")
        assert cal["verified"] is False
        assert [e["event"] for e in cal["events"]] == ["FOMC Rate Decision"]

    @patch("trading_skills.calendar_nasdaq._fetch_rows", return_value=None)
    def test_fetch_failure_on_fomc_day_still_flags_fomc(self, _):
        cal = fetch_us_economic_calendar("2026-10-28")
        assert cal["verified"] is False
        assert cal["events"][0]["event"] == "FOMC Rate Decision"

    @patch("trading_skills.calendar_nasdaq._fetch_rows", side_effect=_fake_rows)
    def test_wrapper_returns_events_list(self, _):
        events = fetch_us_economic_events("2026-10-29")
        assert any(e["event"] == "Initial Jobless Claims" for e in events)


@pytest.mark.manual
class TestLiveFetch:
    def test_fetch_returns_list_or_none(self):
        # Live Nasdaq endpoint; a weekday should return some US events.
        result = fetch_us_economic_events("2026-07-10")
        assert result is None or isinstance(result, list)


def _times(events):
    return {e["event"]: e["time_et"] for e in events}


class TestAlignTimes:
    """Nasdaq's `gmt` column is a fixed UTC-4 clock, so standard-time releases read an hour late.

    Observed 2026-10-30: Initial Jobless Claims for Thu 2026-11-05 (EST) showed 09:30,
    Nonfarm Payrolls for 2026-11-06 showed 09:30; both release at 08:30 ET.
    """

    def test_standard_time_day_is_shifted_back_an_hour(self):
        events = parse_events(
            [
                _row("09:30", "Initial Jobless Claims"),
                _row("09:30", "Continuing Jobless Claims"),
                _row("11:30", "Natural Gas Storage"),
            ]
        )
        aligned, verified = align_times(events, "2026-11-05")
        assert _times(aligned) == {
            "Initial Jobless Claims": "08:30 ET",
            "Continuing Jobless Claims": "08:30 ET",
            "Natural Gas Storage": "10:30 ET",
        }
        assert verified is True

    def test_daylight_time_day_is_unchanged(self):
        events = parse_events(_FEED["2026-10-30"])  # Thu 2026-10-29, claims at 08:30
        aligned, verified = align_times(events, "2026-10-29")
        assert _times(aligned) == _times(events)
        assert verified is True

    def test_feed_on_the_standard_time_clock_is_shifted_forward(self):
        # Should Nasdaq move its clock to UTC-5 after Nov 1, summer-date releases
        # would read an hour early; the anchors measure that too.
        events = parse_events([_row("07:30", "Initial Jobless Claims"), _row("07:30", "GDP")])
        aligned, verified = align_times(events, "2026-10-29")
        assert _times(aligned) == {"Initial Jobless Claims": "08:30 ET", "GDP": "08:30 ET"}
        assert verified is True

    def test_majority_of_anchors_decides(self):
        events = parse_events(
            [
                _row("09:30", "Nonfarm Payrolls"),
                _row("09:30", "Unemployment Rate"),
                _row("11:00", "Michigan Consumer Sentiment"),
                _row("08:30", "Retail Sales"),  # an outlier row
            ]
        )
        aligned, _ = align_times(events, "2026-11-06")
        assert _times(aligned)["Nonfarm Payrolls"] == "08:30 ET"
        assert _times(aligned)["Michigan Consumer Sentiment"] == "10:00 ET"

    def test_no_anchor_uses_the_reference_clock(self):
        utc_minus_5 = timezone(timedelta(hours=-5))
        events = parse_events([_row("08:55", "Redbook")])
        aligned, verified = align_times(events, "2026-11-03", reference=utc_minus_5)
        assert _times(aligned) == {"Redbook": "08:55 ET"}
        assert verified is True

    def test_no_anchor_on_a_standard_time_day_assumes_utc_minus_4(self):
        events = parse_events([_row("09:55", "Redbook")])
        aligned, verified = align_times(events, "2026-11-03")
        assert _times(aligned) == {"Redbook": "08:55 ET"}
        assert verified is False

    def test_no_anchor_on_a_daylight_time_day_is_unchanged(self):
        events = parse_events([_row("08:55", "Redbook")])
        aligned, verified = align_times(events, "2026-10-27")
        assert _times(aligned) == {"Redbook": "08:55 ET"}
        assert verified is False

    def test_events_without_a_time_are_kept(self):
        events = parse_events([_row("", "Some Survey"), _row("09:30", "Initial Jobless Claims")])
        aligned, _ = align_times(events, "2026-11-05")
        assert _times(aligned)["Some Survey"] is None

    def test_anchor_names_match_exactly(self):
        # "Atlanta Fed GDPNow" is a model update with no fixed time, not the GDP release.
        events = parse_events([_row("11:30", "Atlanta Fed GDPNow")])
        _, verified = align_times(events, "2026-11-04")
        assert verified is False


class TestFetchCalendarTimes:
    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_standard_time_day_is_served_in_et(self, mock_rows):
        mock_rows.side_effect = lambda d, t: {
            "2026-11-06": [
                _row("09:30", "Initial Jobless Claims"),
                _row("11:30", "Natural Gas Storage"),
            ]
        }.get(d)
        cal = fetch_us_economic_calendar("2026-11-05")
        assert _times(cal["events"]) == {
            "Initial Jobless Claims": "08:30 ET",
            "Natural Gas Storage": "10:30 ET",
        }
        assert cal["times_verified"] is True

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_printed_release_is_not_mistaken_for_a_future_one(self, mock_rows):
        # 08:45 ET on Thu 2026-11-05: claims (08:30 ET, listed 09:30) already printed.
        mock_rows.side_effect = lambda d, t: {
            "2026-11-06": [_row("09:30", "Initial Jobless Claims", "201K")]
        }.get(d)
        now = datetime(2026, 11, 5, 8, 45, tzinfo=NY)
        cal = fetch_us_economic_calendar("2026-11-05", now=now)
        assert cal is not None
        assert cal["verified"] is True

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_fomc_decision_stays_at_two_pm(self, mock_rows):
        mock_rows.side_effect = lambda d, t: {
            "2026-12-10": [_row("11:30", "Crude Oil Inventories")]
        }.get(d)
        cal = fetch_us_economic_calendar("2026-12-09")
        assert _times(cal["events"])["Crude Oil Inventories"] == "10:30 ET"
        fomc = [e for e in cal["events"] if e["event"] == "FOMC Rate Decision"]
        assert fomc and fomc[0]["time_et"] == "14:00 ET"

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_day_without_anchors_is_measured_on_a_nearby_thursday(self, mock_rows):
        # Tue 2026-11-03 holds only Redbook. Thu 2026-11-05 (same standard-time
        # period) lists claims at 08:30, so the feed's clock is already ET-correct
        # there and Redbook's 08:55 must not be shifted.
        mock_rows.side_effect = lambda d, t: {
            "2026-11-04": [_row("08:55", "Redbook")],
            "2026-11-06": [_row("08:30", "Initial Jobless Claims")],
        }.get(d)
        cal = fetch_us_economic_calendar("2026-11-03")
        assert _times(cal["events"]) == {"Redbook": "08:55 ET"}
        assert cal["times_verified"] is True

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_reference_thursday_stays_in_the_same_clock_period(self, mock_rows):
        # Mon 2026-11-02 is standard time. Thu 2026-10-29 (daylight time) implies a
        # UTC-5 clock, Thu 2026-11-05 (standard time) a UTC-4 clock; only the
        # latter applies to Monday.
        mock_rows.side_effect = lambda d, t: {
            "2026-11-03": [_row("10:45", "S&P Global Manufacturing PMI")],
            "2026-10-30": [_row("07:30", "Initial Jobless Claims")],
            "2026-11-06": [_row("09:30", "Initial Jobless Claims")],
        }.get(d)
        cal = fetch_us_economic_calendar("2026-11-02")
        assert _times(cal["events"]) == {"S&P Global Manufacturing PMI": "09:45 ET"}
        assert cal["times_verified"] is True

    @patch("trading_skills.calendar_nasdaq._fetch_rows")
    def test_unmeasurable_clock_marks_times_unverified(self, mock_rows):
        mock_rows.side_effect = lambda d, t: {"2026-11-04": [_row("09:55", "Redbook")]}.get(d)
        cal = fetch_us_economic_calendar("2026-11-03")
        assert _times(cal["events"]) == {"Redbook": "08:55 ET"}
        assert cal["times_verified"] is False

    @patch("trading_skills.calendar_nasdaq._fetch_rows", return_value=None)
    def test_fomc_only_day_has_exact_times(self, _):
        cal = fetch_us_economic_calendar("2026-12-09")
        assert cal["times_verified"] is True

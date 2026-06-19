# ABOUTME: Tests for the fallback data-source layer (SEC EDGAR, NASDAQ, fallback chain).
# ABOUTME: Pure parser tests on real response shapes + chain logic, all mocked (no network).

from datetime import date
from unittest.mock import MagicMock, patch

from trading_skills.data_sources import _http, fallback, nasdaq, sec_edgar

# --- Real response shapes (captured from live probes) ---

TICKERS = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K", "8-K", "8-K", "10-Q", "8-K"],
            "filingDate": ["2026-05-20", "2026-05-08", "2026-02-25", "2026-02-26", "2024-08-28"],
            "items": ["2.02,9.01", "5.02", "2.02,9.01", "", "2.02,9.01"],
        }
    }
}

SURPRISE = {
    "data": {
        "earningsSurpriseTable": {
            "rows": [
                {
                    "fiscalQtrEnd": "Apr 2026",
                    "dateReported": "5/20/2026",
                    "eps": 1.87,
                    "consensusForecast": "1.7",
                    "percentageSurprise": "10",
                },
                {
                    "fiscalQtrEnd": "Jan 2026",
                    "dateReported": "2/25/2026",
                    "eps": 1.57,
                    "consensusForecast": "1.45",
                    "percentageSurprise": "8.28",
                },
            ]
        }
    }
}

NVDA_DATES = [
    "2026-05-20",
    "2026-02-25",
    "2025-11-19",
    "2025-08-27",
    "2025-05-28",
    "2025-02-26",
    "2024-11-20",
    "2024-08-28",
]


class TestSecEdgar:
    def test_cik_map_found(self):
        assert sec_edgar._parse_cik_map(TICKERS, "nvda") == "0001045810"
        assert sec_edgar._parse_cik_map(TICKERS, "AAPL") == "0000320193"

    def test_cik_map_missing(self):
        assert sec_edgar._parse_cik_map(TICKERS, "ZZZZ") is None
        assert sec_edgar._parse_cik_map(None, "NVDA") is None

    def test_cik_map_dual_class_separator(self):
        # SEC stores BRK-B; a caller passing BRK.B should still resolve.
        tickers = {"0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY"}}
        assert sec_edgar._parse_cik_map(tickers, "BRK.B") == "0001067983"

    def test_earnings_dates_only_item_202(self):
        # Only 8-K with item 2.02 are earnings; 5.02 and 10-Q excluded.
        out = sec_edgar._parse_earnings_dates(SUBMISSIONS)
        assert out == ["2026-05-20", "2026-02-25", "2024-08-28"]

    def test_earnings_dates_limit(self):
        assert sec_edgar._parse_earnings_dates(SUBMISSIONS, limit=2) == ["2026-05-20", "2026-02-25"]

    def test_earnings_dates_bad_input(self):
        assert sec_edgar._parse_earnings_dates(None) == []
        assert sec_edgar._parse_earnings_dates({}) == []


class TestNasdaq:
    def test_to_float(self):
        assert nasdaq._to_float("$1.87") == 1.87
        assert nasdaq._to_float("10") == 10.0
        assert nasdaq._to_float("8.28%") == 8.28
        assert nasdaq._to_float(None) is None
        assert nasdaq._to_float("N/A") is None

    def test_to_float_accounting_negatives(self):
        # Parenthesized values are negatives (loss quarters / negative surprise).
        assert nasdaq._to_float("($0.12)") == -0.12
        assert nasdaq._to_float("(8.28)") == -8.28
        assert nasdaq._to_float("(1,234.56)") == -1234.56

    def test_parse_surprise(self):
        rows = nasdaq._parse_surprise(SURPRISE)
        assert len(rows) == 2
        assert rows[0]["eps_actual"] == 1.87
        assert rows[0]["eps_estimate"] == 1.7
        assert rows[0]["surprise_pct"] == 10.0

    def test_parse_surprise_empty(self):
        assert nasdaq._parse_surprise(None) == []
        assert nasdaq._parse_surprise({"data": {}}) == []

    def test_parse_next_date_vendor_gap(self):
        gap = {
            "data": {
                "reportText": "Our vendor hasn't provided...",
                "announcement": "Earnings announcement* for NVDA: ",
            }
        }
        assert nasdaq._parse_next_date(gap) is None

    def test_parse_next_date_found(self):
        d = {"data": {"announcement": "Earnings announcement* for NVDA: Aug 26, 2026"}}
        assert nasdaq._parse_next_date(d) == "2026-08-26"
        d2 = {"data": {"announcement": "for NVDA: August 26, 2026"}}
        assert nasdaq._parse_next_date(d2) == "2026-08-26"

    def test_parse_next_date_sept_abbreviation(self):
        # NASDAQ's 4-letter "Sept" is parsed neither by %b nor %B without help.
        d = {"data": {"announcement": "for X: Sept 7, 2026"}}
        assert nasdaq._parse_next_date(d) == "2026-09-07"


class TestEstimateNextFromDates:
    def test_estimates_from_cadence(self):
        # NVDA real cadence -> median gap ~91d, next from 2026-05-20.
        est = fallback._estimate_next_from_dates(NVDA_DATES, today=date(2026, 6, 19))
        assert est == "2026-08-19"
        assert date.fromisoformat(est) > date(2026, 6, 19)

    def test_too_few_dates(self):
        assert fallback._estimate_next_from_dates(["2026-05-20"], today=date(2026, 6, 19)) is None

    def test_stale_history_not_projected(self):
        # Most recent report is ~2 years old -> don't fabricate a far-future date.
        stale = ["2024-05-20", "2024-02-21", "2023-11-21", "2023-08-23"]
        assert fallback._estimate_next_from_dates(stale, today=date(2026, 6, 19)) is None

    def test_irregular_gaps_rejected(self):
        # Gaps far outside a quarterly cadence are filtered out.
        assert (
            fallback._estimate_next_from_dates(
                ["2026-05-20", "2020-01-01"], today=date(2026, 6, 19)
            )
            is None
        )


class TestResolveChain:
    def test_yf_value_short_circuits(self):
        out = fallback.resolve_next_earnings_date("NVDA", yf_value="2026-08-26 16:00:00")
        assert out == {"date": "2026-08-26", "source": "yfinance"}

    @patch("trading_skills.data_sources.fallback.sec_edgar.get_earnings_release_dates")
    @patch("trading_skills.data_sources.fallback.nasdaq.get_next_earnings_date")
    def test_falls_back_to_sec_estimate(self, mock_nasdaq, mock_sec):
        mock_nasdaq.return_value = None
        mock_sec.return_value = NVDA_DATES
        out = fallback.resolve_next_earnings_date("NVDA", today=date(2026, 6, 19))
        assert out["source"] == "sec_estimate"
        assert out["date"] == "2026-08-19"

    @patch("trading_skills.data_sources.fallback.nasdaq.get_next_earnings_date")
    def test_uses_nasdaq_when_available(self, mock_nasdaq):
        mock_nasdaq.return_value = "2026-08-26"
        out = fallback.resolve_next_earnings_date("NVDA", today=date(2026, 6, 19))
        assert out == {"date": "2026-08-26", "source": "nasdaq"}

    @patch("trading_skills.data_sources.fallback.sec_edgar.get_earnings_release_dates")
    @patch("trading_skills.data_sources.fallback.nasdaq.get_next_earnings_date")
    def test_nasdaq_past_date_rejected(self, mock_nasdaq, mock_sec):
        # A "last reported" date from NASDAQ must not be returned as upcoming.
        mock_nasdaq.return_value = "2026-05-20"  # in the past relative to today
        mock_sec.return_value = NVDA_DATES
        out = fallback.resolve_next_earnings_date("NVDA", today=date(2026, 6, 19))
        assert out["source"] == "sec_estimate"

    @patch("trading_skills.data_sources.fallback.nasdaq.get_next_earnings_date")
    @patch("trading_skills.data_sources.fallback.sec_edgar.get_earnings_release_dates")
    def test_all_sources_fail(self, mock_sec, mock_nasdaq):
        mock_nasdaq.return_value = None
        mock_sec.return_value = []
        out = fallback.resolve_next_earnings_date("ZZZZ", today=date(2026, 6, 19))
        assert out == {"date": None, "source": None}

    def test_resolve_past_dates_uses_yf_when_given(self):
        out = fallback.resolve_past_earnings_dates(
            "NVDA", yf_dates=["2026-05-20 16:00", "2026-02-25"]
        )
        assert out == ["2026-05-20", "2026-02-25"]

    @patch("trading_skills.data_sources.fallback.sec_edgar.get_earnings_release_dates")
    def test_resolve_past_dates_falls_back_to_sec(self, mock_sec):
        mock_sec.return_value = NVDA_DATES
        out = fallback.resolve_past_earnings_dates("NVDA")
        assert out == NVDA_DATES


class TestHttpLayer:
    def test_caches_successful_response(self):
        _http.clear_cache()
        with patch("trading_skills.data_sources._http.requests") as mock_req:
            resp = MagicMock(status_code=200)
            resp.json.return_value = {"a": 1}
            mock_req.get.return_value = resp
            url = "https://example.test/cache-1"
            assert _http.get_json(url) == {"a": 1}
            assert _http.get_json(url) == {"a": 1}
            assert mock_req.get.call_count == 1  # second call served from cache

    def test_non_200_returns_none(self):
        _http.clear_cache()
        with patch("trading_skills.data_sources._http.requests") as mock_req:
            mock_req.get.return_value = MagicMock(status_code=404)
            assert _http.get_json("https://example.test/missing", retries=0) is None

    def test_exception_returns_none(self):
        _http.clear_cache()
        with patch("trading_skills.data_sources._http.requests") as mock_req:
            mock_req.get.side_effect = Exception("boom")
            assert _http.get_json("https://example.test/boom", retries=0) is None

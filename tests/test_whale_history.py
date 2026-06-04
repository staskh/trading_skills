# ABOUTME: Unit tests for historical OPRA flatfile whale detection (pure, no network/S3).
# ABOUTME: Covers ticker/CSV parsing, modified-z outlier detection, 0DTE exclusion, config error.

from datetime import date

import pytest

from trading_skills.massive.whale_history import (
    FlatfileConfigError,
    _credentials,
    _months_of,
    _parse_day_csv,
    detect_whales,
    parse_strike,
)


class TestParseStrike:
    def test_strike_divides_by_1000(self):
        assert parse_strike("00500000") == 500.0
        assert parse_strike("00731500") == 731.5


class TestMonthsOf:
    def test_spans_year_boundary(self):
        assert _months_of(date(2025, 11, 15), date(2026, 2, 3)) == [
            "2025/11",
            "2025/12",
            "2026/01",
            "2026/02",
        ]

    def test_single_month(self):
        assert _months_of(date(2026, 6, 1), date(2026, 6, 30)) == ["2026/06"]


class TestParseDayCsv:
    HEADER = "ticker,volume,open,close,high,low,window_start,transactions\n"

    def test_filters_to_underlying_and_parses_fields(self):
        body = self.HEADER + "\n".join(
            [
                "O:SPY260612C00500000,100,2.0,2.5,3.0,1.9,1780459200000000000,40",
                "O:SPYG260612C00500000,9,1.0,1.0,1.0,1.0,1780459200000000000,2",  # SPYG, not SPY
                "O:SPY260612P00480000,50,1.0,1.2,1.3,0.9,1780459200000000000,10",
            ]
        )
        rows = _parse_day_csv(body, "SPY")
        assert len(rows) == 2  # SPYG excluded by exact underlying match
        call = next(r for r in rows if r["type"] == "call")
        assert call["strike"] == 500.0
        assert call["expiry"] == "2026-06-12"
        assert call["invested"] == 2.5 * 100 * 100  # close*vol*100

    def test_skips_malformed_rows(self):
        body = self.HEADER + "O:SPY260612C00500000,oops,,,,,,\n"
        assert _parse_day_csv(body, "SPY") == []


class TestDetectWhales:
    def _rows(self, n_normal, big_invested, expiry="2026-06-12"):
        rows = [
            {
                "ticker": f"O:SPY260612C0050{i:04d}",
                "type": "call",
                "strike": 500.0 + i,
                "expiry": expiry,
                "close": 1.0,
                "volume": 100,
                "transactions": 5,
                "invested": 10_000.0,
            }
            for i in range(n_normal)
        ]
        rows.append(
            {
                "ticker": "O:SPY260612C00600000",
                "type": "call",
                "strike": 600.0,
                "expiry": expiry,
                "close": 5.0,
                "volume": 200_000,
                "transactions": 9000,
                "invested": big_invested,
            }
        )
        return rows

    def test_outlier_above_floor_flagged(self):
        rows = self._rows(50, 5_000_000.0)
        whales = detect_whales(
            rows, sigma_z=3.5, floor=500_000.0, exclude_0dte=False, trade_date="2026-06-01"
        )
        assert len(whales) == 1
        assert whales[0]["invested"] == 5_000_000.0
        assert whales[0]["break_even"] == 605.0  # call: strike + close

    def test_below_floor_not_flagged(self):
        rows = self._rows(50, 5_000_000.0)
        whales = detect_whales(
            rows, sigma_z=3.5, floor=10_000_000.0, exclude_0dte=False, trade_date="2026-06-01"
        )
        assert whales == []

    def test_exclude_0dte_drops_same_day_expiry(self):
        # the big contract expires on the trade date -> excluded
        rows = self._rows(50, 5_000_000.0, expiry="2026-06-01")
        whales = detect_whales(
            rows, sigma_z=3.5, floor=500_000.0, exclude_0dte=True, trade_date="2026-06-01"
        )
        assert whales == []

    def test_empty_rows_returns_empty(self):
        assert detect_whales([], 3.5, 500_000.0, False, "2026-06-01") == []


class TestCredentials:
    def test_missing_creds_raises(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_S3_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("MASSIVE_S3_SECRET_ACCESS_KEY", raising=False)
        with pytest.raises(FlatfileConfigError):
            _credentials()

    def test_defaults_endpoint_and_bucket(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_S3_ACCESS_KEY_ID", "k")
        monkeypatch.setenv("MASSIVE_S3_SECRET_ACCESS_KEY", "s")
        monkeypatch.delenv("MASSIVE_S3_ENDPOINT", raising=False)
        monkeypatch.delenv("MASSIVE_S3_BUCKET", raising=False)
        akid, secret, endpoint, bucket = _credentials()
        assert (akid, secret) == ("k", "s")
        assert endpoint == "https://files.massive.com"
        assert bucket == "flatfiles"

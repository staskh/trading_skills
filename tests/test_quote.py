# ABOUTME: Tests for stock quote module using real Yahoo Finance data.
# ABOUTME: Validates price retrieval, field presence, and error handling.

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from trading_skills.quote import get_quote

NY = ZoneInfo("America/New_York")


class TestGetQuote:
    """Tests for get_quote with real Yahoo Finance data."""

    def test_valid_symbol(self):
        result = get_quote("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["price"] is not None
        assert isinstance(result["price"], (int, float))
        assert result["price"] > 0

    def test_expected_fields(self):
        result = get_quote("MSFT")
        expected = [
            "symbol",
            "name",
            "price",
            "volume",
            "market_cap",
            "as_of_session",
            "market_open_now",
            "market_state",
            "pre_market",
            "post_market",
        ]
        for field in expected:
            assert field in result, f"Missing field: {field}"

    def test_numeric_fields(self):
        result = get_quote("AAPL")
        assert isinstance(result["volume"], (int, type(None)))
        assert isinstance(result["market_cap"], (int, float, type(None)))

    def test_invalid_symbol(self):
        result = get_quote("INVALIDXYZ123")
        assert "error" in result

    def test_case_insensitive(self):
        result = get_quote("aapl")
        assert result["symbol"] == "AAPL"


class TestSessionFromQuoteData:
    """Live: the session label comes from Yahoo's own timestamp."""

    def test_as_of_session_is_a_past_or_current_date(self):
        result = get_quote("AAPL")
        session = date.fromisoformat(result["as_of_session"])
        assert session <= datetime.now(NY).date()


def _epoch(y, mo, d, h, mi):
    return int(datetime(y, mo, d, h, mi, tzinfo=NY).timestamp())


# Yahoo quote payload as served after the 2026-10-29 close (DELL), trimmed to the
# fields get_quote reads. Session fields are overridden per test.
_INFO = {
    "regularMarketPrice": 392.10,
    "currentPrice": 392.10,
    "regularMarketChange": -34.81,
    "regularMarketChangePercent": -8.15394,
    "regularMarketTime": _epoch(2026, 10, 29, 16, 0),
    "marketState": "POST",
    "shortName": "Dell Technologies Inc.",
}


def _quote(**overrides):
    with patch("trading_skills.quote.yf.Ticker") as ticker:
        ticker.return_value.info = {**_INFO, **overrides}
        return get_quote("DELL")


class TestAsOfSession:
    """A pre-market quote must name the session its change describes, not today."""

    def test_session_is_the_date_of_the_regular_market_timestamp(self):
        assert _quote()["as_of_session"] == "2026-10-29"

    def test_premarket_quote_names_the_prior_session(self):
        # 09:12 ET on Fri 10/30: Yahoo's regular fields still carry Thursday's close.
        result = _quote(marketState="PRE")
        assert result["as_of_session"] == "2026-10-29"
        assert result["market_state"] == "PRE"

    def test_stale_feed_names_the_session_it_actually_holds(self):
        # A feed stuck on Monday's close is labeled Monday, whatever today is.
        result = _quote(regularMarketTime=_epoch(2026, 10, 26, 16, 0))
        assert result["as_of_session"] == "2026-10-26"

    def test_missing_timestamp_is_none(self):
        assert _quote(regularMarketTime=None)["as_of_session"] is None


class TestExtendedHours:
    def test_premarket_price_and_move(self):
        result = _quote(
            marketState="PRE",
            preMarketPrice=401.50,
            preMarketChange=9.40,
            preMarketChangePercent=2.3973,
            preMarketTime=_epoch(2026, 10, 30, 9, 12),
        )
        assert result["pre_market"] == {
            "price": 401.50,
            "change": 9.40,
            "change_percent": 2.3973,
            "time": "2026-10-30 09:12 ET",
        }

    def test_postmarket_price_and_move(self):
        result = _quote(
            postMarketPrice=391.80,
            postMarketChange=-0.30,
            postMarketChangePercent=-0.0765,
            postMarketTime=_epoch(2026, 10, 29, 17, 45),
        )
        assert result["post_market"] == {
            "price": 391.80,
            "change": -0.30,
            "change_percent": -0.0765,
            "time": "2026-10-29 17:45 ET",
        }

    def test_absent_extended_hours_are_none(self):
        result = _quote()
        assert result["pre_market"] is None
        assert result["post_market"] is None

    def test_extended_price_without_timestamp_has_no_time(self):
        result = _quote(postMarketPrice=391.80)
        assert result["post_market"]["time"] is None

# ABOUTME: Tests for news sentiment module using real Yahoo Finance data.
# ABOUTME: Validates news article retrieval, the RSS fallback and field structure.

from types import SimpleNamespace
from unittest.mock import patch

from trading_skills.news import get_news, parse_rss

# Trimmed from https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL on 2026-10-30.
# Items arrive out of date order.
_RSS = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<rss version="2.0">
    <channel>
        <title>Yahoo! Finance: AAPL News</title>
        <item>
            <description>Apple (AAPL) is set to report Q4 earnings.</description>
            <guid>7b7fc854-7f20-4f5c-aa9b-82073ae1b623</guid>
            <link>https://finance.yahoo.com/video/what-to-expect-from-apples-q4-earnings.html</link>
            <pubDate>Fri, 30 Oct 2026 20:23:02 +0000</pubDate>
            <title>What to expect from Apple's Q4 earnings this Monday</title>
        </item>
        <item>
            <description>Apple reclaimed the top market-cap spot.</description>
            <guid>fbda8d1c-a985-38a9-b415-2445548bef07</guid>
            <link>https://finance.yahoo.com/markets/stocks/articles/apple-overtakes-nvidia.html</link>
            <pubDate>Fri, 30 Oct 2026 21:47:53 +0000</pubDate>
            <title>Apple overtakes Nvidia to become world's most valuable company</title>
        </item>
        <item>
            <guid>d0bc23d0-115b-314d-8989-07ca797bebfa</guid>
            <link>https://www.investors.com/news/dow-jones-futures.html</link>
            <title>Dow Jones Futures: Stock Market Sells Off</title>
        </item>
    </channel>
</rss>"""

_EMPTY_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Yahoo! Finance:  News</title></channel></rss>"""


def _feed(status=200, content=_RSS):
    return SimpleNamespace(status_code=status, content=content)


def _ticker(news=None, error=None):
    """A yfinance Ticker stand-in whose .news returns `news` or raises `error`."""

    class _Ticker:
        @property
        def news(self):
            if error:
                raise error
            return news or []

    return _Ticker()


class TestGetNews:
    """Tests for get_news with real data."""

    def test_valid_symbol(self):
        result = get_news("AAPL")
        assert result["symbol"] == "AAPL"
        assert "articles" in result

    def test_valid_symbol_has_articles(self):
        """Ticker.news is empty upstream (#146); the RSS fallback must still find news."""
        result = get_news("AAPL")
        assert result["count"] > 0
        assert result["source"] in ("yfinance", "yahoo-rss")

    def test_limit_parameter(self):
        result = get_news("AAPL", limit=3)
        assert len(result["articles"]) <= 3

    def test_article_fields(self):
        result = get_news("AAPL", limit=5)
        if result["articles"]:
            article = result["articles"][0]
            assert "title" in article
            assert "publisher" in article
            assert "date" in article
            assert "link" in article

    def test_count_matches_articles(self):
        result = get_news("AAPL", limit=5)
        assert result["count"] == len(result["articles"])

    def test_no_news_symbol(self):
        """Symbol with no news returns empty articles list."""
        result = get_news("INVALIDXYZ123")
        assert "articles" in result or "error" in result


class TestParseRss:
    def test_items_newest_first_with_et_dates(self):
        articles = parse_rss(_RSS)
        assert [a["date"] for a in articles] == [
            "2026-10-30 17:47 ET",
            "2026-10-30 16:23 ET",
            None,
        ]

    def test_fields(self):
        article = parse_rss(_RSS)[0]
        assert article == {
            "title": "Apple overtakes Nvidia to become world's most valuable company",
            "publisher": "finance.yahoo.com",
            "date": "2026-10-30 17:47 ET",
            "link": "https://finance.yahoo.com/markets/stocks/articles/apple-overtakes-nvidia.html",
            "type": None,
        }

    def test_publisher_is_the_link_host(self):
        assert parse_rss(_RSS)[-1]["publisher"] == "www.investors.com"

    def test_empty_feed(self):
        assert parse_rss(_EMPTY_RSS) == []


class TestSourceFallback:
    def test_yfinance_news_is_used_when_present(self):
        item = {
            "content": {
                "title": "Apple beats",
                "pubDate": "2026-10-30T20:23:02Z",
                "provider": {"displayName": "Reuters"},
                "canonicalUrl": {"url": "https://example.com/a"},
                "contentType": "STORY",
            }
        }
        with patch("trading_skills.news.yf.Ticker", return_value=_ticker([item])):
            result = get_news("AAPL")
        assert result["source"] == "yfinance"
        assert result["articles"][0]["date"] == "2026-10-30 16:23 ET"
        assert result["articles"][0]["publisher"] == "Reuters"

    def test_empty_yfinance_falls_back_to_rss(self):
        with (
            patch("trading_skills.news.yf.Ticker", return_value=_ticker([])),
            patch("trading_skills.news.requests.get", return_value=_feed()),
        ):
            result = get_news("AAPL", limit=2)
        assert result["source"] == "yahoo-rss"
        assert result["count"] == 2
        assert result["articles"][0]["date"] == "2026-10-30 17:47 ET"
        assert "tagged" in result["note"]

    def test_failing_yfinance_falls_back_to_rss(self):
        with (
            patch("trading_skills.news.yf.Ticker", return_value=_ticker(error=RuntimeError("404"))),
            patch("trading_skills.news.requests.get", return_value=_feed()),
        ):
            result = get_news("AAPL")
        assert result["source"] == "yahoo-rss"
        assert result["count"] == 3

    def test_both_sources_empty_is_no_news(self):
        """No news must still report count, so callers see one response shape."""
        with (
            patch("trading_skills.news.yf.Ticker", return_value=_ticker([])),
            patch("trading_skills.news.requests.get", return_value=_feed(content=_EMPTY_RSS)),
        ):
            result = get_news("AAPL")
        assert result["count"] == 0
        assert result["articles"] == []
        assert result["message"] == "No news found"
        assert "error" not in result

    def test_both_sources_failing_is_an_error(self):
        with (
            patch("trading_skills.news.yf.Ticker", return_value=_ticker(error=RuntimeError("404"))),
            patch("trading_skills.news.requests.get", return_value=_feed(status=503)),
        ):
            result = get_news("AAPL")
        assert "error" in result
        assert "404" in result["error"]
        assert "503" in result["error"]

    def test_unparseable_feed_counts_as_a_failure(self):
        with (
            patch("trading_skills.news.yf.Ticker", return_value=_ticker([])),
            patch("trading_skills.news.requests.get", return_value=_feed(content=b"<html>")),
        ):
            result = get_news("AAPL")
        assert "error" in result

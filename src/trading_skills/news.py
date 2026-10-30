# ABOUTME: Fetches recent news for a stock from Yahoo Finance.
# ABOUTME: Returns headlines, publishers, and dates; falls back to Yahoo's RSS feed.

import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
import yfinance as yf

NY = ZoneInfo("America/New_York")

# Per-ticker headline feed. yfinance's Ticker.news posts to an endpoint that now
# answers 404, which yfinance turns into an empty list (issue #146).
_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_RSS_NOTE = (
    "Yahoo RSS items are tagged to the ticker, not necessarily about it; "
    "some are market-wide stories."
)


def _et(moment: datetime) -> str:
    return moment.astimezone(NY).strftime("%Y-%m-%d %H:%M ET")


def _yfinance_articles(symbol: str) -> list[dict]:
    """Articles from yfinance's Ticker.news, in the order Yahoo returns them."""
    articles = []
    for item in yf.Ticker(symbol).news or []:
        # yfinance now nests data under 'content'
        content = item.get("content", {})

        # Parse pubDate (ISO format: 2026-02-04T17:30:54Z)
        pub_date_str = content.get("pubDate")
        if pub_date_str:
            try:
                pub_date = _et(datetime.fromisoformat(pub_date_str.replace("Z", "+00:00")))
            except (ValueError, AttributeError):
                pub_date = pub_date_str
        else:
            pub_date = None

        # Get provider name
        provider = content.get("provider", {})
        publisher = provider.get("displayName")

        # Get link from canonicalUrl
        canonical = content.get("canonicalUrl", {})
        link = canonical.get("url")

        articles.append(
            {
                "title": content.get("title"),
                "publisher": publisher,
                "date": pub_date,
                "link": link,
                "type": content.get("contentType"),
            }
        )
    return articles


def parse_rss(xml: bytes) -> list[dict]:
    """Articles from a Yahoo RSS headline feed, newest first (undated items last).

    The feed has no publisher field, so the link's host stands in for it.
    """
    dated = []
    for item in ET.fromstring(xml).iter("item"):
        raw_date = item.findtext("pubDate")
        published = parsedate_to_datetime(raw_date) if raw_date else None
        link = item.findtext("link")
        dated.append(
            (
                published,
                {
                    "title": item.findtext("title"),
                    "publisher": urlparse(link).hostname if link else None,
                    "date": _et(published) if published else None,
                    "link": link,
                    "type": None,
                },
            )
        )
    dated.sort(key=lambda pair: (pair[0] is None, -(pair[0].timestamp() if pair[0] else 0)))
    return [article for _, article in dated]


def _rss_articles(symbol: str, timeout: float = 10.0) -> list[dict]:
    """Articles from the per-ticker RSS feed; raises on an HTTP or parse failure."""
    resp = requests.get(
        _RSS_URL,
        params={"s": symbol, "region": "US", "lang": "en-US"},
        headers=_HEADERS,
        timeout=timeout,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return parse_rss(resp.content)


def get_news(symbol: str, limit: int = 10) -> dict:
    """Fetch recent news for a symbol.

    Tries yfinance's Ticker.news, then Yahoo's RSS feed. Reports "No news found"
    only when both sources answered with no articles; if neither returned articles
    and either failed, returns an error naming the failures, since an empty answer
    from one source cannot vouch for the other.
    """
    symbol = symbol.upper()
    failures = []
    for source, fetch in (("yfinance", _yfinance_articles), ("yahoo-rss", _rss_articles)):
        try:
            articles = fetch(symbol)
        except Exception as e:
            failures.append(f"{source}: {e}")
            continue
        if articles:
            result = {
                "symbol": symbol,
                "count": len(articles[:limit]),
                "articles": articles[:limit],
                "source": source,
            }
            if source == "yahoo-rss":
                result["note"] = _RSS_NOTE
            return result

    if failures:
        return {"error": f"Failed to fetch news: {'; '.join(failures)}"}
    return {"symbol": symbol, "count": 0, "articles": [], "message": "No news found"}

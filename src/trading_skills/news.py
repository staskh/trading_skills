# ABOUTME: Fetches recent news for a stock from Yahoo Finance.
# ABOUTME: Returns headlines, publishers, and dates.

from datetime import datetime

import yfinance as yf


def get_news(symbol: str, limit: int = 10) -> dict:
    """Fetch recent news for a symbol."""
    ticker = yf.Ticker(symbol)

    try:
        news = ticker.news
    except Exception as e:
        return {"error": f"Failed to fetch news: {e}"}

    if not news:
        return {"symbol": symbol.upper(), "articles": [], "message": "No news found"}

    articles = []
    for item in news[:limit]:
        # yfinance now nests data under 'content'
        content = item.get("content", {})

        # Parse pubDate (ISO format: 2026-02-04T17:30:54Z)
        pub_date_str = content.get("pubDate")
        if pub_date_str:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00")).strftime(
                    "%Y-%m-%d %H:%M"
                )
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

    return {
        "symbol": symbol.upper(),
        "count": len(articles),
        "articles": articles,
    }

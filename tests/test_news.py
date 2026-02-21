# ABOUTME: Tests for news sentiment module using real Yahoo Finance data.
# ABOUTME: Validates news article retrieval and field structure.


from trading_skills.news import get_news


class TestGetNews:
    """Tests for get_news with real data."""

    def test_valid_symbol(self):
        result = get_news("AAPL")
        assert result["symbol"] == "AAPL"
        assert "articles" in result

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

# ABOUTME: Tests for stock quote module using real Yahoo Finance data.
# ABOUTME: Validates price retrieval, field presence, and error handling.


from trading_skills.quote import get_quote


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
        for field in ["symbol", "name", "price", "volume", "market_cap"]:
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

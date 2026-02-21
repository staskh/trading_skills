# ABOUTME: Tests for price history module using real Yahoo Finance data.
# ABOUTME: Validates OHLCV data retrieval for various periods and intervals.


from trading_skills.history import get_history


class TestGetHistory:
    """Tests for get_history with real Yahoo Finance data."""

    def test_default_period(self):
        result = get_history("AAPL")
        assert result["symbol"] == "AAPL"
        assert result["period"] == "1mo"
        assert result["interval"] == "1d"
        assert len(result["data"]) > 0

    def test_custom_period(self):
        result = get_history("AAPL", period="5d")
        assert result["period"] == "5d"
        assert len(result["data"]) <= 7

    def test_custom_interval(self):
        result = get_history("AAPL", period="5d", interval="1h")
        assert result["interval"] == "1h"
        assert len(result["data"]) > 0

    def test_ohlcv_fields(self):
        result = get_history("AAPL", period="5d")
        for row in result["data"]:
            for field in ["date", "open", "high", "low", "close", "volume"]:
                assert field in row, f"Missing field: {field}"

    def test_price_sanity(self):
        """High >= Low for all rows."""
        result = get_history("AAPL", period="5d")
        for row in result["data"]:
            assert row["high"] >= row["low"]

    def test_count_matches_data(self):
        result = get_history("AAPL", period="5d")
        assert result["count"] == len(result["data"])

    def test_invalid_symbol(self):
        result = get_history("INVALIDXYZ123")
        assert "error" in result

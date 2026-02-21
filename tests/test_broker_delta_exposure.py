# ABOUTME: Tests for delta exposure module format_markdown function.
# ABOUTME: Validates summary and full report markdown generation.


from trading_skills.broker.delta_exposure import format_markdown


class TestFormatMarkdown:
    """Tests for delta exposure markdown formatting."""

    def test_connection_error(self):
        data = {"connected": False, "error": "Could not connect"}
        result = format_markdown(data)
        assert "Error:" in result
        assert "Could not connect" in result

    def test_summary_report(self):
        data = {
            "connected": True,
            "accounts": ["U123456"],
            "position_count": 3,
            "positions": [
                {
                    "account": "U123456",
                    "symbol": "AAPL",
                    "sec_type": "OPT",
                    "strike": 200,
                    "expiry": "20250321",
                    "right": "C",
                    "qty": -5,
                    "spot": 195.0,
                    "delta": -0.3500,
                    "multiplier": 100,
                    "raw_notional": -97500.0,
                    "delta_notional": -34125.0,
                },
                {
                    "account": "U123456",
                    "symbol": "AAPL",
                    "sec_type": "STK",
                    "qty": 500,
                    "spot": 195.0,
                    "delta": 1.0,
                    "multiplier": 1,
                    "raw_notional": 97500.0,
                    "delta_notional": 97500.0,
                },
                {
                    "account": "U123456",
                    "symbol": "GOOG",
                    "sec_type": "OPT",
                    "strike": 180,
                    "expiry": "20250321",
                    "right": "P",
                    "qty": -3,
                    "spot": 175.0,
                    "delta": 0.2500,
                    "multiplier": 100,
                    "raw_notional": -52500.0,
                    "delta_notional": -13125.0,
                },
            ],
            "summary": {
                "total_long_delta_notional": 97500.0,
                "total_short_delta_notional": -47250.0,
                "net_delta_notional": 50250.0,
                "by_account": {
                    "U123456": {"long": 97500.0, "short": -47250.0},
                },
                "by_underlying": {
                    "AAPL": {"long": 97500.0, "short": -34125.0, "net": 63375.0},
                    "GOOG": {"long": 0, "short": -13125.0, "net": -13125.0},
                },
            },
        }
        result = format_markdown(data)
        assert "Delta-Adjusted Notional Exposure Report" in result
        assert "U123456" in result
        assert "AAPL" in result
        assert "GOOG" in result
        assert "Top Long Delta Exposures" in result
        assert "Top Short Delta Exposures" in result

    def test_full_report(self):
        data = {
            "connected": True,
            "accounts": ["U123456"],
            "position_count": 1,
            "positions": [
                {
                    "account": "U123456",
                    "symbol": "AAPL",
                    "sec_type": "STK",
                    "qty": 100,
                    "spot": 195.0,
                    "delta": 1.0,
                    "multiplier": 1,
                    "raw_notional": 19500.0,
                    "delta_notional": 19500.0,
                },
            ],
            "summary": {
                "total_long_delta_notional": 19500.0,
                "total_short_delta_notional": 0.0,
                "net_delta_notional": 19500.0,
                "by_account": {"U123456": {"long": 19500.0, "short": 0.0}},
                "by_underlying": {"AAPL": {"long": 19500.0, "short": 0.0, "net": 19500.0}},
            },
        }
        result = format_markdown(data, full_report=True)
        assert "Detailed Positions by Account" in result
        assert "Detailed Positions by Symbol" in result
        assert "Long Positions" in result

    def test_full_report_with_short_positions(self):
        data = {
            "connected": True,
            "accounts": ["U123456"],
            "position_count": 2,
            "positions": [
                {
                    "account": "U123456",
                    "symbol": "AAPL",
                    "sec_type": "STK",
                    "qty": 100,
                    "spot": 195.0,
                    "delta": 1.0,
                    "multiplier": 1,
                    "raw_notional": 19500.0,
                    "delta_notional": 19500.0,
                },
                {
                    "account": "U123456",
                    "symbol": "AAPL",
                    "sec_type": "OPT",
                    "strike": 200,
                    "expiry": "20250321",
                    "right": "C",
                    "qty": -1,
                    "spot": 195.0,
                    "delta": -0.45,
                    "multiplier": 100,
                    "raw_notional": -19500.0,
                    "delta_notional": -8775.0,
                },
            ],
            "summary": {
                "total_long_delta_notional": 19500.0,
                "total_short_delta_notional": -8775.0,
                "net_delta_notional": 10725.0,
                "by_account": {"U123456": {"long": 19500.0, "short": -8775.0}},
                "by_underlying": {"AAPL": {"long": 19500.0, "short": -8775.0, "net": 10725.0}},
            },
        }
        result = format_markdown(data, full_report=True)
        assert "Short Positions" in result

    def test_empty_portfolio(self):
        data = {
            "connected": True,
            "accounts": ["U123456"],
            "position_count": 0,
            "positions": [],
            "summary": {
                "total_long_delta_notional": 0.0,
                "total_short_delta_notional": 0.0,
                "net_delta_notional": 0.0,
                "by_account": {},
                "by_underlying": {},
            },
        }
        result = format_markdown(data)
        assert "Delta-Adjusted Notional Exposure Report" in result
        assert "$0" in result

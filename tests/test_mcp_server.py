#!/usr/bin/env python3
# ABOUTME: Tests for MCP server tools.
# ABOUTME: Verifies all trading tools are accessible and return expected data.


class TestMCPServerImport:
    """Test that MCP server imports correctly."""

    def test_server_loads(self):
        """MCP server loads without errors."""
        from mcp_server.server import mcp

        assert mcp.name == "trading-skills"

    def test_all_tools_registered(self):
        """All expected tools are registered."""
        from mcp_server.server import mcp

        tools = mcp._tool_manager._tools
        expected_tools = [
            "stock_quote",
            "price_history",
            "news_sentiment",
            "fundamentals",
            "piotroski_score",
            "earnings_calendar",
            "technical_indicators",
            "price_correlation",
            "risk_assessment",
            "option_expiries",
            "option_chain",
            "option_greeks",
            "spread_vertical",
            "spread_diagonal",
            "spread_straddle",
            "spread_strangle",
            "spread_iron_condor",
            "scan_bullish",
            "scan_pmcc",
            "ib_account",
            "ib_portfolio",
            "ib_find_short_roll",
            "ib_portfolio_action_report",
        ]
        for tool_name in expected_tools:
            assert tool_name in tools, f"Missing tool: {tool_name}"


class TestMarketDataTools:
    """Test market data tools."""

    def test_stock_quote(self):
        """stock_quote returns price data."""
        from mcp_server.server import stock_quote

        result = stock_quote("AAPL")
        assert "symbol" in result
        assert result["symbol"] == "AAPL"
        assert "price" in result or "error" in result

    def test_price_history(self):
        """price_history returns OHLCV data."""
        from mcp_server.server import price_history

        result = price_history("AAPL", period="5d", interval="1d")
        assert "symbol" in result
        if "data" in result:
            assert len(result["data"]) > 0
            assert "open" in result["data"][0]


class TestTechnicalTools:
    """Test technical analysis tools."""

    def test_technical_indicators_single(self):
        """technical_indicators works for single symbol."""
        from mcp_server.server import technical_indicators

        result = technical_indicators("AAPL", period="1mo", indicators="rsi")
        assert "symbol" in result
        assert "indicators" in result
        assert "rsi" in result["indicators"]

    def test_price_correlation(self):
        """price_correlation returns correlation matrix."""
        from mcp_server.server import price_correlation

        result = price_correlation("AAPL,MSFT", period="1mo")
        assert "correlation_matrix" in result
        assert "AAPL" in result["correlation_matrix"]
        assert "MSFT" in result["correlation_matrix"]["AAPL"]


class TestOptionsTools:
    """Test options tools."""

    def test_option_expiries(self):
        """option_expiries returns list of dates."""
        from mcp_server.server import option_expiries

        result = option_expiries("AAPL")
        assert "symbol" in result
        assert "expiries" in result or "error" in result

    def test_option_greeks(self):
        """option_greeks calculates Greeks."""
        from mcp_server.server import option_greeks

        result = option_greeks(spot=150.0, strike=155.0, option_type="call", dte=30)
        assert "greeks" in result
        assert "delta" in result["greeks"]
        assert "gamma" in result["greeks"]
        assert "theta" in result["greeks"]


class TestScannerTools:
    """Test scanner tools."""

    def test_scan_bullish_single(self):
        """scan_bullish works for single symbol."""
        from mcp_server.server import scan_bullish

        result = scan_bullish("AAPL", period="1mo")
        # Single symbol returns score directly
        assert "symbol" in result or "error" in result
        if "symbol" in result:
            assert "score" in result


class TestIBTools:
    """Test IB tools (will fail gracefully if TWS not running)."""

    def test_ib_account_handles_no_connection(self):
        """ib_account returns error when IB not connected."""
        import asyncio

        from mcp_server.server import ib_account

        result = asyncio.run(ib_account(port=7497))
        # Should return connected=False or error when IB not running
        assert "connected" in result or "error" in result
        if "connected" in result:
            assert result["connected"] is False or "error" in result

    def test_ib_portfolio_handles_no_connection(self):
        """ib_portfolio returns error when IB not connected."""
        import asyncio

        from mcp_server.server import ib_portfolio

        result = asyncio.run(ib_portfolio(port=7497))
        # Should return connected=False or error when IB not running
        assert "connected" in result or "error" in result

    def test_ib_find_short_roll_handles_no_connection(self):
        """ib_find_short_roll returns error when IB not connected."""
        import asyncio

        from mcp_server.server import ib_find_short_roll

        result = asyncio.run(ib_find_short_roll("AAPL", port=7497))
        # Should return error when IB not running
        assert "error" in result

    def test_ib_portfolio_action_report_handles_no_connection(self):
        """ib_portfolio_action_report returns error when IB not connected."""
        import asyncio
        import tempfile

        from mcp_server.server import ib_portfolio_action_report

        with tempfile.TemporaryDirectory() as tmpdir:
            result = asyncio.run(ib_portfolio_action_report(output_dir=tmpdir, port=7497))
        # Should return error when IB not running
        assert "error" in result

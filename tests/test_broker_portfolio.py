# ABOUTME: Tests for IB portfolio module with mocked IB connection.
# ABOUTME: Validates position formatting and connection error handling.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from trading_skills.broker.portfolio import get_portfolio


class TestGetPortfolio:
    """Tests for get_portfolio with mocked IB."""

    def test_connection_failure(self):
        """Handles connection failure gracefully."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("refused"))
            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497))
            assert result["connected"] is False
            assert "error" in result

    def test_invalid_account(self):
        """Handles invalid account selection."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497, account="WRONG"))
            assert result["connected"] is True
            assert "error" in result

    def test_empty_portfolio(self):
        """Handles empty portfolio."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.positions.return_value = []
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497))
            assert result["connected"] is True
            assert result["position_count"] == 0
            assert result["positions"] == []

    def test_stock_position(self):
        """Formats stock position correctly."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()

            # Mock stock position
            pos = MagicMock()
            pos.account = "U123456"
            pos.contract.symbol = "AAPL"
            pos.contract.secType = "STK"
            pos.contract.currency = "USD"
            pos.position = 100
            pos.avgCost = 150.0
            mock_ib.positions.return_value = [pos]

            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497))
            assert result["connected"] is True
            assert result["position_count"] == 1
            assert result["positions"][0]["symbol"] == "AAPL"
            assert result["positions"][0]["quantity"] == 100

    def test_all_accounts(self):
        """Fetches positions from all accounts."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456", "U789012"]
            mock_ib.positions.return_value = []
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497, all_accounts=True))
            assert result["connected"] is True
            assert result["accounts"] == ["U123456", "U789012"]

    def test_option_position(self):
        """Formats option position with underlying price."""
        with (
            patch("trading_skills.broker.connection.IB") as MockIB,
            patch("trading_skills.broker.connection.fetch_with_timeout") as mock_conn_fetch,
            patch("trading_skills.broker.portfolio.fetch_with_timeout") as mock_port_fetch,
        ):
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()

            # Mock option position
            pos = MagicMock()
            pos.account = "U123456"
            pos.contract.symbol = "AAPL"
            pos.contract.secType = "OPT"
            pos.contract.currency = "USD"
            pos.contract.strike = 200.0
            pos.contract.lastTradeDateOrContractMonth = "20250321"
            pos.contract.right = "C"
            pos.contract.multiplier = "100"
            pos.position = -5
            pos.avgCost = 250.0  # $2.50 per share * 100
            mock_ib.positions.return_value = [pos]

            # Mock spot price fetch (via connection.fetch_spot_prices)
            mock_ticker = MagicMock()
            mock_ticker.contract.symbol = "AAPL"
            mock_ticker.marketPrice.return_value = 195.0
            mock_conn_fetch.side_effect = [
                [pos.contract],  # qualifyContracts for stocks
                [mock_ticker],  # reqTickers for stocks
            ]

            # Mock option price fetch (via portfolio's direct fetch_with_timeout)
            mock_opt_ticker = MagicMock()
            mock_opt_ticker.contract = pos.contract
            mock_opt_ticker.marketPrice.return_value = 3.50
            mock_port_fetch.side_effect = [
                [pos.contract],  # qualifyContracts for options
                [mock_opt_ticker],  # reqTickers for options
            ]

            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497))
            assert result["connected"] is True
            assert result["position_count"] == 1
            opt = result["positions"][0]
            assert opt["symbol"] == "AAPL"
            assert opt["sec_type"] == "OPT"
            assert opt["strike"] == 200.0
            assert opt["right"] == "C"
            assert opt["quantity"] == -5

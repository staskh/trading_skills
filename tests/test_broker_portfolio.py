# ABOUTME: Tests for IB portfolio module with mocked IB connection.
# ABOUTME: Validates position formatting and connection error handling.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from trading_skills.broker.portfolio import get_portfolio


def _make_portfolio_item(
    account="U123456",
    symbol="AAPL",
    sec_type="STK",
    currency="USD",
    position=100,
    average_cost=150.0,
    market_price=155.0,
    market_value=15500.0,
    unrealized_pnl=500.0,
    multiplier="",
    strike=None,
    expiry=None,
    right=None,
):
    item = MagicMock()
    item.account = account
    item.contract.symbol = symbol
    item.contract.secType = sec_type
    item.contract.currency = currency
    item.contract.multiplier = multiplier
    item.contract.strike = strike
    item.contract.lastTradeDateOrContractMonth = expiry
    item.contract.right = right
    item.position = position
    item.averageCost = average_cost
    item.marketPrice = market_price
    item.marketValue = market_value
    item.unrealizedPNL = unrealized_pnl
    return item


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
            mock_ib.reqAccountUpdatesAsync = AsyncMock()
            mock_ib.portfolio.return_value = []
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
            mock_ib.reqAccountUpdatesAsync = AsyncMock()
            mock_ib.portfolio.return_value = []
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
            mock_ib.reqAccountUpdatesAsync = AsyncMock()
            mock_ib.portfolio.return_value = [
                _make_portfolio_item(
                    symbol="AAPL",
                    sec_type="STK",
                    position=100,
                    average_cost=150.0,
                    market_price=155.0,
                    market_value=15500.0,
                    unrealized_pnl=500.0,
                )
            ]
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497))
            assert result["connected"] is True
            assert result["position_count"] == 1
            pos = result["positions"][0]
            assert pos["symbol"] == "AAPL"
            assert pos["quantity"] == 100
            assert pos["avg_cost"] == 150.0
            assert pos["market_price"] == 155.0
            assert pos["unrealized_pnl"] == 500.0

    def test_all_accounts(self):
        """Fetches positions from all accounts."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456", "U789012"]
            mock_ib.reqAccountUpdatesAsync = AsyncMock()
            mock_ib.portfolio.return_value = []
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_portfolio(port=7497, all_accounts=True))
            assert result["connected"] is True
            assert result["accounts"] == ["U123456", "U789012"]

    def test_option_position(self):
        """Formats option position with underlying price."""
        with (
            patch("trading_skills.broker.connection.IB") as MockIB,
            patch("trading_skills.broker.portfolio.fetch_spot_prices") as mock_spot,
        ):
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.reqAccountUpdatesAsync = AsyncMock()
            mock_ib.portfolio.return_value = [
                _make_portfolio_item(
                    symbol="AAPL",
                    sec_type="OPT",
                    position=-5,
                    average_cost=250.0,  # $2.50/share * 100 multiplier
                    market_price=3.50,
                    market_value=-1750.0,
                    unrealized_pnl=-600.0,
                    multiplier="100",
                    strike=200.0,
                    expiry="20250321",
                    right="C",
                )
            ]
            mock_ib.disconnect = MagicMock()
            mock_spot.return_value = {"AAPL": 195.0}
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
            assert opt["avg_cost"] == 2.50
            assert opt["market_price"] == 3.50
            assert opt["underlying_price"] == 195.0

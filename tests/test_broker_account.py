# ABOUTME: Tests for IB account summary module with mocked IB connection.
# ABOUTME: Validates account data formatting and connection error handling.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from trading_skills.broker.account import get_account_summary


class TestGetAccountSummary:
    """Tests for get_account_summary with mocked IB."""

    def test_connection_failure(self):
        """Handles connection failure gracefully."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("refused"))
            MockIB.return_value = mock_ib

            result = asyncio.run(get_account_summary(port=7497))
            assert result["connected"] is False
            assert "error" in result

    def test_no_managed_accounts(self):
        """Handles no managed accounts."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = []
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_account_summary(port=7497))
            assert result["connected"] is True
            assert "error" in result

    def test_successful_summary(self):
        """Successful account summary fetch."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()

            # Mock account summary items
            item1 = MagicMock()
            item1.tag = "NetLiquidation"
            item1.value = "100000.00"
            item1.currency = "USD"

            item2 = MagicMock()
            item2.tag = "TotalCashValue"
            item2.value = "25000.00"
            item2.currency = "USD"

            item3 = MagicMock()
            item3.tag = "BuyingPower"
            item3.value = "200000.00"
            item3.currency = "USD"

            mock_ib.accountSummaryAsync = AsyncMock(return_value=[item1, item2, item3])
            MockIB.return_value = mock_ib

            result = asyncio.run(get_account_summary(port=7497))
            assert result["connected"] is True
            assert result["account"] == "U123456"
            assert result["summary"]["net_liquidation"] == "100000.00"
            assert result["summary"]["total_cash"] == "25000.00"

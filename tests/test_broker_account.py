# ABOUTME: Tests for IB account summary module with mocked IB connection.
# ABOUTME: Validates single-account, multi-account, and error handling.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from trading_skills.broker.account import get_account_summary


def _make_summary_item(tag, value, currency="USD"):
    item = MagicMock()
    item.tag = tag
    item.value = value
    item.currency = currency
    return item


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

    def test_successful_summary_default_first_account(self):
        """Default behavior fetches first account."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456", "U789012"]
            mock_ib.disconnect = MagicMock()

            mock_ib.accountSummaryAsync = AsyncMock(
                return_value=[
                    _make_summary_item("NetLiquidation", "100000.00"),
                    _make_summary_item("TotalCashValue", "25000.00"),
                    _make_summary_item("BuyingPower", "200000.00"),
                ]
            )
            MockIB.return_value = mock_ib

            result = asyncio.run(get_account_summary(port=7497))
            assert result["connected"] is True
            assert len(result["accounts"]) == 1
            assert result["accounts"][0]["account"] == "U123456"
            assert result["accounts"][0]["summary"]["net_liquidation"] == "100000.00"
            assert result["accounts"][0]["summary"]["total_cash"] == "25000.00"

    def test_all_accounts(self):
        """Fetches all managed accounts when all_accounts=True."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456", "U789012"]
            mock_ib.disconnect = MagicMock()

            mock_ib.accountSummaryAsync = AsyncMock(
                side_effect=[
                    [
                        _make_summary_item("NetLiquidation", "100000.00"),
                        _make_summary_item("TotalCashValue", "25000.00"),
                    ],
                    [
                        _make_summary_item("NetLiquidation", "50000.00"),
                        _make_summary_item("TotalCashValue", "10000.00"),
                    ],
                ]
            )
            MockIB.return_value = mock_ib

            result = asyncio.run(get_account_summary(port=7497, all_accounts=True))
            assert result["connected"] is True
            assert len(result["accounts"]) == 2
            assert result["accounts"][0]["account"] == "U123456"
            assert result["accounts"][0]["summary"]["net_liquidation"] == "100000.00"
            assert result["accounts"][1]["account"] == "U789012"
            assert result["accounts"][1]["summary"]["net_liquidation"] == "50000.00"

    def test_specific_account(self):
        """Fetches a specific account by ID."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456", "U789012"]
            mock_ib.disconnect = MagicMock()

            mock_ib.accountSummaryAsync = AsyncMock(
                return_value=[
                    _make_summary_item("NetLiquidation", "50000.00"),
                    _make_summary_item("TotalCashValue", "10000.00"),
                ]
            )
            MockIB.return_value = mock_ib

            result = asyncio.run(get_account_summary(port=7497, account="U789012"))
            assert result["connected"] is True
            assert len(result["accounts"]) == 1
            assert result["accounts"][0]["account"] == "U789012"

    def test_specific_account_not_found(self):
        """Returns error when requested account doesn't exist."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_account_summary(port=7497, account="U999999"))
            assert result["connected"] is True
            assert "error" in result
            assert "U999999" in result["error"]

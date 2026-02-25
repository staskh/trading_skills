# ABOUTME: Tests for IB connection utilities used by all broker modules.
# ABOUTME: Validates context manager, position fetching, normalization, and spot price fetching.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_positions,
    fetch_spot_prices,
    ib_connection,
    normalize_positions,
)

MODULE = "trading_skills.broker.connection"


class TestIbConnection:
    """Tests for ib_connection async context manager."""

    def test_connects_and_disconnects(self):
        with patch(f"{MODULE}.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            async def run():
                async with ib_connection(7496, 1) as ib:
                    return ib

            result = asyncio.run(run())
            assert result is mock_ib
            mock_ib.connectAsync.assert_called_once_with(
                host="127.0.0.1", port=7496, clientId=1
            )
            mock_ib.disconnect.assert_called_once()

    def test_disconnects_on_exception(self):
        with patch(f"{MODULE}.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            async def run():
                async with ib_connection(7496, 1):
                    raise ValueError("test error")

            with pytest.raises(ValueError, match="test error"):
                asyncio.run(run())

            mock_ib.disconnect.assert_called_once()

    def test_raises_connection_error_on_failure(self):
        with patch(f"{MODULE}.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock(
                side_effect=ConnectionRefusedError("refused")
            )
            MockIB.return_value = mock_ib

            async def run():
                async with ib_connection(7496, 1):
                    pass

            with pytest.raises(ConnectionError, match="7496"):
                asyncio.run(run())


class TestFetchPositions:
    """Tests for fetch_positions."""

    def test_returns_positions_for_account(self):
        mock_ib = MagicMock()
        pos1 = MagicMock()
        pos1.account = "U123"
        pos2 = MagicMock()
        pos2.account = "U456"
        mock_ib.positions.return_value = [pos1, pos2]

        async def run():
            return await fetch_positions(mock_ib, account="U123", sleep=0)

        result = asyncio.run(run())
        assert result == [pos1]

    def test_returns_all_positions_without_account(self):
        mock_ib = MagicMock()
        pos1 = MagicMock()
        pos1.account = "U123"
        mock_ib.positions.return_value = [pos1]

        async def run():
            return await fetch_positions(mock_ib, sleep=0)

        result = asyncio.run(run())
        assert result == [pos1]


class TestNormalizePositions:
    """Tests for normalize_positions pure function."""

    def _make_position(
        self, symbol, sec_type, qty, avg_cost, strike=0, expiry="", right="", multiplier=""
    ):
        pos = MagicMock()
        pos.account = "U123"
        pos.contract.symbol = symbol
        pos.contract.secType = sec_type
        pos.position = qty
        pos.avgCost = avg_cost
        pos.contract.strike = strike
        pos.contract.lastTradeDateOrContractMonth = expiry
        pos.contract.right = right
        pos.contract.multiplier = multiplier
        return pos

    def test_stock_position(self):
        pos = self._make_position("AAPL", "STK", 100, 150.0)
        result = normalize_positions([pos])
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["sec_type"] == "STK"
        assert result[0]["quantity"] == 100
        assert result[0]["avg_cost"] == 150.0
        assert result[0]["strike"] is None
        assert result[0]["expiry"] is None
        assert result[0]["right"] is None

    def test_option_divides_cost_by_multiplier(self):
        pos = self._make_position(
            "AAPL", "OPT", -5, 250.0,
            strike=200.0, expiry="20250321", right="C", multiplier="100"
        )
        result = normalize_positions([pos])
        assert len(result) == 1
        assert result[0]["avg_cost"] == 2.50
        assert result[0]["strike"] == 200.0
        assert result[0]["expiry"] == "20250321"
        assert result[0]["right"] == "C"

    def test_option_default_multiplier_100(self):
        pos = self._make_position(
            "AAPL", "OPT", 1, 500.0,
            strike=150.0, expiry="20250321", right="P", multiplier=""
        )
        result = normalize_positions([pos])
        assert result[0]["avg_cost"] == 5.0

    def test_fop_divides_cost_by_multiplier(self):
        pos = self._make_position(
            "ES", "FOP", -2, 1000.0,
            strike=5000.0, expiry="20250321", right="P", multiplier="50"
        )
        result = normalize_positions([pos])
        assert result[0]["avg_cost"] == 20.0


class TestFetchSpotPrices:
    """Tests for fetch_spot_prices."""

    def test_fetches_prices(self):
        mock_ib = MagicMock()

        # Mock qualify
        contract1 = MagicMock()
        contract1.symbol = "AAPL"
        mock_ib.qualifyContractsAsync = AsyncMock(return_value=[contract1])

        # Mock tickers
        ticker1 = MagicMock()
        ticker1.contract.symbol = "AAPL"
        ticker1.marketPrice.return_value = 195.50
        mock_ib.reqTickersAsync = AsyncMock(return_value=[ticker1])

        async def run():
            return await fetch_spot_prices(mock_ib, ["AAPL"], timeout=5.0)

        result = asyncio.run(run())
        assert result == {"AAPL": 195.50}

    def test_empty_symbols(self):
        mock_ib = MagicMock()

        async def run():
            return await fetch_spot_prices(mock_ib, [])

        result = asyncio.run(run())
        assert result == {}

    def test_skips_invalid_prices(self):
        mock_ib = MagicMock()
        contract1 = MagicMock()
        mock_ib.qualifyContractsAsync = AsyncMock(return_value=[contract1])

        ticker1 = MagicMock()
        ticker1.contract.symbol = "AAPL"
        ticker1.marketPrice.return_value = -1
        mock_ib.reqTickersAsync = AsyncMock(return_value=[ticker1])

        async def run():
            return await fetch_spot_prices(mock_ib, ["AAPL"], timeout=5.0)

        result = asyncio.run(run())
        assert result == {}

    def test_timeout_returns_empty(self):
        mock_ib = MagicMock()
        mock_ib.qualifyContractsAsync = AsyncMock(side_effect=asyncio.TimeoutError)

        async def run():
            return await fetch_spot_prices(mock_ib, ["AAPL"], timeout=0.1)

        result = asyncio.run(run())
        assert result == {}


class TestClientIds:
    """Tests for CLIENT_IDS registry."""

    def test_no_duplicate_ids(self):
        ids = list(CLIENT_IDS.values())
        assert len(ids) == len(set(ids)), f"Duplicate client IDs: {CLIENT_IDS}"

    def test_all_modules_registered(self):
        expected = {
            "portfolio", "account", "collar", "portfolio_action",
            "delta_exposure", "options_expiries", "options_chain", "roll",
            "consolidate",
        }
        assert set(CLIENT_IDS.keys()) == expected

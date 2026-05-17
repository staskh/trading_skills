# ABOUTME: Tests for IB trade execution fetching with mocked IB connection.
# ABOUTME: Validates API and FlexReport paths, date filtering, and aggregation.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from trading_skills.broker.trades import (
    _aggregate_executions,
    _fetch_from_files,
    _filter_by_date,
    _normalize_fill,
    get_trades,
)


def _make_fill(
    symbol="AAPL",
    sec_type="STK",
    side="BOT",
    shares=100,
    price=150.0,
    avg_price=150.0,
    acct="U123456",
    time_str="2026-02-20T10:30:00",
    exchange="SMART",
    commission=1.0,
    realized_pnl=0.0,
    strike=None,
    expiry=None,
    right=None,
):
    """Create a mock Fill object."""
    fill = MagicMock()

    execution = MagicMock()
    execution.acctNumber = acct
    execution.side = side
    execution.shares = shares
    execution.price = price
    execution.avgPrice = avg_price
    execution.time = MagicMock()
    execution.time.isoformat.return_value = time_str
    execution.exchange = exchange
    fill.execution = execution

    contract = MagicMock()
    contract.symbol = symbol
    contract.secType = sec_type
    contract.strike = strike
    contract.lastTradeDateOrContractMonth = expiry
    contract.right = right
    fill.contract = contract

    cr = MagicMock()
    cr.commission = commission
    cr.realizedPNL = realized_pnl
    fill.commissionReport = cr

    return fill


class TestNormalizeFill:
    """Tests for _normalize_fill."""

    def test_stock_fill(self):
        fill = _make_fill(symbol="AAPL", sec_type="STK", side="BOT", shares=100, price=150.0)
        result = _normalize_fill(fill)
        assert result["symbol"] == "AAPL"
        assert result["secType"] == "STK"
        assert result["side"] == "BOT"
        assert result["quantity"] == 100
        assert result["price"] == 150.0
        assert result["account"] == "U123456"
        assert "strike" not in result

    def test_option_fill(self):
        fill = _make_fill(
            symbol="AAPL",
            sec_type="OPT",
            side="SLD",
            shares=1,
            price=3.50,
            strike=155.0,
            expiry="20260320",
            right="C",
        )
        result = _normalize_fill(fill)
        assert result["secType"] == "OPT"
        assert result["strike"] == 155.0
        assert result["expiry"] == "20260320"
        assert result["right"] == "C"

    def test_no_commission_report(self):
        fill = _make_fill()
        fill.commissionReport = None
        result = _normalize_fill(fill)
        assert result["commission"] is None
        assert result["realizedPnL"] is None


class TestFilterByDate:
    """Tests for _filter_by_date."""

    def test_filters_within_range(self):
        executions = [
            {"datetime": "2026-01-15T10:00:00", "symbol": "A"},
            {"datetime": "2026-02-20T10:00:00", "symbol": "B"},
            {"datetime": "2026-03-15T10:00:00", "symbol": "C"},
        ]
        result = _filter_by_date(executions, "2026-02-01", "2026-02-28")
        assert len(result) == 1
        assert result[0]["symbol"] == "B"

    def test_includes_boundary_dates(self):
        executions = [
            {"datetime": "2026-02-01T00:00:00", "symbol": "A"},
            {"datetime": "2026-02-28T23:59:59", "symbol": "B"},
        ]
        result = _filter_by_date(executions, "2026-02-01", "2026-02-28")
        assert len(result) == 2

    def test_no_datetime_kept(self):
        executions = [{"symbol": "A"}]
        result = _filter_by_date(executions, "2026-01-01", "2026-12-31")
        assert len(result) == 1


class TestAggregateExecutions:
    """Tests for _aggregate_executions."""

    def test_single_symbol(self):
        executions = [
            {
                "symbol": "AAPL",
                "side": "BOT",
                "quantity": 100,
                "commission": 1.0,
                "realizedPnL": 0.0,
                "datetime": "2026-02-20T10:00:00",
            },
            {
                "symbol": "AAPL",
                "side": "SLD",
                "quantity": 50,
                "commission": 1.0,
                "realizedPnL": 500.0,
                "datetime": "2026-02-21T10:00:00",
            },
        ]
        result = _aggregate_executions(executions)
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["total_bought"] == 100
        assert result[0]["total_sold"] == 50
        assert result[0]["net_quantity"] == 50
        assert result[0]["total_commission"] == 2.0
        assert result[0]["total_realized_pnl"] == 500.0
        assert result[0]["trade_count"] == 2
        assert result[0]["first_trade"] == "2026-02-20T10:00:00"
        assert result[0]["last_trade"] == "2026-02-21T10:00:00"

    def test_multiple_symbols_sorted(self):
        executions = [
            {
                "symbol": "TSLA",
                "side": "BOT",
                "quantity": 10,
                "commission": 1.0,
                "realizedPnL": 0.0,
                "datetime": "2026-02-20T10:00:00",
            },
            {
                "symbol": "AAPL",
                "side": "BOT",
                "quantity": 100,
                "commission": 1.0,
                "realizedPnL": 0.0,
                "datetime": "2026-02-20T10:00:00",
            },
        ]
        result = _aggregate_executions(executions)
        assert len(result) == 2
        assert result[0]["symbol"] == "AAPL"
        assert result[1]["symbol"] == "TSLA"

    def test_empty_executions(self):
        result = _aggregate_executions([])
        assert result == []

    def test_none_commission(self):
        executions = [
            {
                "symbol": "AAPL",
                "side": "BOT",
                "quantity": 100,
                "commission": None,
                "realizedPnL": None,
                "datetime": "2026-02-20T10:00:00",
            },
        ]
        result = _aggregate_executions(executions)
        assert result[0]["total_commission"] == 0.0
        assert result[0]["total_realized_pnl"] == 0.0


class TestGetTradesAPI:
    """Tests for get_trades using reqExecutionsAsync."""

    def test_connection_failure(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError("refused"))
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497))
            assert result["connected"] is False
            assert "error" in result

    def test_no_managed_accounts(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = []
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497))
            assert result["connected"] is True
            assert "error" in result

    def test_successful_fetch_default_account(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456", "U789012"]
            mock_ib.disconnect = MagicMock()

            fill = _make_fill(
                symbol="AAPL",
                side="BOT",
                shares=100,
                price=150.0,
                time_str="2026-02-20T10:30:00",
                acct="U123456",
            )
            mock_ib.reqExecutionsAsync = AsyncMock(return_value=[fill])
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497))
            assert result["connected"] is True
            assert result["source"] == "reqExecutionsAsync"
            assert result["execution_count"] == 1
            assert result["executions"][0]["symbol"] == "AAPL"
            assert result["executions"][0]["side"] == "BOT"
            assert result["filters"]["account"] == "U123456"
            assert "data_limitation" in result

    def test_all_accounts(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456", "U789012"]
            mock_ib.disconnect = MagicMock()

            fill1 = _make_fill(symbol="AAPL", acct="U123456", time_str="2026-02-20T10:00:00")
            fill2 = _make_fill(symbol="TSLA", acct="U789012", time_str="2026-02-20T11:00:00")
            mock_ib.reqExecutionsAsync = AsyncMock(side_effect=[[fill1], [fill2]])
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497, all_accounts=True))
            assert result["connected"] is True
            assert result["execution_count"] == 2
            assert result["filters"]["account"] == ["U123456", "U789012"]

    def test_specific_account_not_found(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497, account="U999999"))
            assert result["connected"] is True
            assert "error" in result
            assert "U999999" in result["error"]

    def test_symbol_filter(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()

            fill = _make_fill(symbol="AAPL", time_str="2026-02-20T10:30:00")
            mock_ib.reqExecutionsAsync = AsyncMock(return_value=[fill])
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497, symbol="AAPL"))
            assert result["connected"] is True
            assert result["filters"]["symbol"] == "AAPL"

    def test_lowercase_symbol_normalized_to_upper_on_api_path(self):
        """Lowercase --symbol must be normalized before it reaches
        ExecutionFilter.symbol, otherwise IB returns no matches (IB symbols are
        uppercase). The filters echo must report the normalized value too, so
        result shape is consistent regardless of input casing or source."""
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()
            mock_ib.reqExecutionsAsync = AsyncMock(return_value=[])
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497, symbol="aapl"))
            assert result["filters"]["symbol"] == "AAPL"
            # ExecutionFilter must receive the uppercased symbol.
            exec_filter = mock_ib.reqExecutionsAsync.call_args.args[0]
            assert exec_filter.symbol == "AAPL"

    def test_date_filtering(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()

            fill_in = _make_fill(symbol="AAPL", time_str="2026-02-15T10:30:00")
            fill_out = _make_fill(symbol="TSLA", time_str="2025-12-01T10:30:00")
            mock_ib.reqExecutionsAsync = AsyncMock(return_value=[fill_in, fill_out])
            MockIB.return_value = mock_ib

            result = asyncio.run(
                get_trades(port=7497, start_date="2026-02-01", end_date="2026-02-28")
            )
            assert result["execution_count"] == 1
            assert result["executions"][0]["symbol"] == "AAPL"

    def test_summary_included(self):
        with patch("trading_skills.broker.connection.IB") as MockIB:
            mock_ib = MagicMock()
            mock_ib.connectAsync = AsyncMock()
            mock_ib.managedAccounts.return_value = ["U123456"]
            mock_ib.disconnect = MagicMock()

            fill1 = _make_fill(
                symbol="AAPL",
                side="BOT",
                shares=100,
                time_str="2026-02-20T10:00:00",
                commission=1.0,
                realized_pnl=0.0,
            )
            fill2 = _make_fill(
                symbol="AAPL",
                side="SLD",
                shares=50,
                time_str="2026-02-21T10:00:00",
                commission=1.0,
                realized_pnl=250.0,
            )
            mock_ib.reqExecutionsAsync = AsyncMock(return_value=[fill1, fill2])
            MockIB.return_value = mock_ib

            result = asyncio.run(get_trades(port=7497))
            assert len(result["summary"]) == 1
            summary = result["summary"][0]
            assert summary["symbol"] == "AAPL"
            assert summary["total_bought"] == 100
            assert summary["total_sold"] == 50
            assert summary["trade_count"] == 2


class TestGetTradesFlex:
    """Tests for get_trades using FlexReport."""

    def test_flex_report_fetch(self):
        with patch("trading_skills.broker.trades.FlexReport", create=True) as MockFlexReport:
            mock_trade = MagicMock()
            mock_trade.symbol = "AAPL"
            mock_trade.assetCategory = "STK"
            mock_trade.quantity = 100
            mock_trade.tradePrice = 150.0
            mock_trade.dateTime = "2026-02-20T10:00:00"
            mock_trade.exchange = "SMART"
            mock_trade.ibCommission = 1.0
            mock_trade.fifoPnlRealized = 0.0
            mock_trade.accountId = "U123456"

            mock_report = MagicMock()
            mock_report.extract.return_value = [mock_trade]
            MockFlexReport.return_value = mock_report

            # Patch the import inside _fetch_via_flex
            with patch.dict("sys.modules", {"ib_async": MagicMock(FlexReport=MockFlexReport)}):
                with patch("trading_skills.broker.trades._fetch_via_flex") as mock_flex:
                    mock_flex.return_value = {
                        "connected": True,
                        "source": "FlexReport",
                        "filters": {
                            "start_date": "2026-01-01",
                            "end_date": "2026-02-28",
                            "symbol": None,
                            "account": "all",
                        },
                        "execution_count": 1,
                        "executions": [
                            {
                                "account": "U123456",
                                "symbol": "AAPL",
                                "secType": "STK",
                                "side": "BOT",
                                "quantity": 100.0,
                                "price": 150.0,
                                "avgPrice": 150.0,
                                "datetime": "2026-02-20T10:00:00",
                                "exchange": "SMART",
                                "commission": 1.0,
                                "realizedPnL": 0.0,
                            }
                        ],
                        "summary": [
                            {
                                "symbol": "AAPL",
                                "total_bought": 100.0,
                                "total_sold": 0.0,
                                "net_quantity": 100.0,
                                "total_commission": 1.0,
                                "total_realized_pnl": 0.0,
                                "trade_count": 1,
                                "first_trade": "2026-02-20T10:00:00",
                                "last_trade": "2026-02-20T10:00:00",
                            }
                        ],
                    }

                    result = asyncio.run(
                        get_trades(
                            port=7497,
                            all_accounts=True,
                            flex_token="TOKEN",
                            flex_query_id="QID",
                        )
                    )
                    assert result["connected"] is True
                    assert result["source"] == "FlexReport"
                    assert result["execution_count"] == 1


class TestFetchFromFiles:
    """Tests for _fetch_from_files error handling on bad XML inputs."""

    def test_missing_file_returns_structured_error(self, tmp_path):
        missing = tmp_path / "nope.xml"
        result = _fetch_from_files(
            files=[str(missing)],
            account=None,
            all_accounts=False,
            symbol=None,
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
        assert result["connected"] is False
        assert "File not found" in result["error"]
        assert str(missing) in result["error"]

    def test_malformed_xml_returns_structured_error(self, tmp_path):
        bad = tmp_path / "bad.xml"
        bad.write_text("<FlexQueryResponse><Trade tradeID='1'", encoding="utf-8")
        result = _fetch_from_files(
            files=[str(bad)],
            account=None,
            all_accounts=False,
            symbol=None,
            start_date="2026-01-01",
            end_date="2026-12-31",
        )
        assert result["connected"] is False
        assert "Malformed FlexReport XML" in result["error"]
        assert str(bad) in result["error"]

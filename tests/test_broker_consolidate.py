# ABOUTME: Tests for trade consolidation module pure logic functions.
# ABOUTME: Validates position determination, row consolidation, and reports.

import csv
import tempfile
from pathlib import Path

from trading_skills.broker.consolidate import (
    consolidate_rows,
    determine_position,
    format_date,
    format_money,
    generate_csv,
    generate_markdown,
    read_csv_files,
)


class TestDeterminePosition:
    """Tests for position type determination."""

    def test_sell_open_is_short(self):
        assert determine_position("SELL", "O") == "SHORT"

    def test_buy_open_is_long(self):
        assert determine_position("BUY", "O") == "LONG"

    def test_buy_close_is_close_short(self):
        assert determine_position("BUY", "C") == "CLOSE_SHORT"

    def test_sell_close_is_close_long(self):
        assert determine_position("SELL", "C") == "CLOSE_LONG"

    def test_case_insensitive(self):
        assert determine_position("sell", "o") == "SHORT"
        assert determine_position("buy", "c") == "CLOSE_SHORT"

    def test_whitespace_stripped(self):
        assert determine_position("  SELL  ", "  O  ") == "SHORT"


class TestFormatDate:
    """Tests for date formatting."""

    def test_valid_yyyymmdd(self):
        assert format_date("20250321") == "2025-03-21"

    def test_short_string_passthrough(self):
        assert format_date("2025") == "2025"

    def test_already_formatted(self):
        assert format_date("2025-03-21") == "2025-03-21"


class TestFormatMoney:
    """Tests for money formatting."""

    def test_positive(self):
        assert format_money(1234.56) == "$1,234.56"

    def test_negative_is_red(self):
        result = format_money(-500.00)
        assert "color:red" in result
        assert "$-500.00" in result

    def test_bold(self):
        result = format_money(100.00, bold=True)
        assert "**$100.00**" in result

    def test_negative_bold(self):
        result = format_money(-100.00, bold=True)
        assert "color:red" in result
        assert "**" in result

    def test_zero(self):
        assert format_money(0.00) == "$0.00"


class TestConsolidateRows:
    """Tests for row consolidation logic."""

    def _make_row(
        self,
        underlying,
        symbol,
        date,
        strike,
        put_call,
        buy_sell,
        open_close,
        qty,
        proceeds,
        net_cash,
        commission,
        pnl,
    ):
        return {
            "UnderlyingSymbol": underlying,
            "Symbol": symbol,
            "TradeDate": date,
            "Strike": strike,
            "Put/Call": put_call,
            "Buy/Sell": buy_sell,
            "Open/CloseIndicator": open_close,
            "Quantity": str(qty),
            "Proceeds": str(proceeds),
            "NetCash": str(net_cash),
            "IBCommission": str(commission),
            "FifoPnlRealized": str(pnl),
            "ClientAccountID": "U123",
            "Description": "Test",
            "Expiry": "20250321",
        }

    def test_single_row(self):
        rows = [
            self._make_row(
                "AAPL", "AAPL250321C200", "20250101", "200", "C", "SELL", "O", 1, 500, 500, -1.5, 0
            )
        ]
        result = consolidate_rows(rows)
        assert len(result) == 1
        assert result[0]["Position"] == "SHORT"
        assert result[0]["Quantity"] == 1.0

    def test_aggregation(self):
        rows = [
            self._make_row(
                "AAPL",
                "AAPL250321C200",
                "20250101",
                "200",
                "C",
                "SELL",
                "O",
                2,
                1000,
                1000,
                -3.0,
                0,
            ),
            self._make_row(
                "AAPL",
                "AAPL250321C200",
                "20250101",
                "200",
                "C",
                "SELL",
                "O",
                3,
                1500,
                1500,
                -4.5,
                0,
            ),
        ]
        result = consolidate_rows(rows)
        assert len(result) == 1
        assert result[0]["Quantity"] == 5.0
        assert result[0]["Proceeds"] == 2500.0
        assert result[0]["IBCommission"] == -7.5

    def test_different_symbols_not_grouped(self):
        rows = [
            self._make_row(
                "AAPL", "AAPL250321C200", "20250101", "200", "C", "SELL", "O", 1, 500, 500, -1.5, 0
            ),
            self._make_row(
                "GOOG", "GOOG250321C150", "20250101", "150", "C", "SELL", "O", 1, 300, 300, -1.5, 0
            ),
        ]
        result = consolidate_rows(rows)
        assert len(result) == 2

    def test_sorted_by_underlying_date_symbol(self):
        rows = [
            self._make_row(
                "GOOG", "GOOG250321C150", "20250101", "150", "C", "SELL", "O", 1, 300, 300, -1.5, 0
            ),
            self._make_row(
                "AAPL", "AAPL250321C200", "20250101", "200", "C", "SELL", "O", 1, 500, 500, -1.5, 0
            ),
        ]
        result = consolidate_rows(rows)
        assert result[0]["UnderlyingSymbol"] == "AAPL"
        assert result[1]["UnderlyingSymbol"] == "GOOG"


class TestReadCsvFiles:
    """Tests for CSV file reading."""

    def test_reads_valid_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "trades.csv"
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "UnderlyingSymbol",
                        "Symbol",
                        "TradeDate",
                        "Strike",
                        "Put/Call",
                        "Buy/Sell",
                        "Open/CloseIndicator",
                        "Quantity",
                        "Proceeds",
                        "NetCash",
                        "IBCommission",
                        "FifoPnlRealized",
                        "ClientAccountID",
                        "Description",
                        "Expiry",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "UnderlyingSymbol": "AAPL",
                        "Symbol": "AAPL250321C200",
                        "TradeDate": "20250101",
                        "Strike": "200",
                        "Put/Call": "C",
                        "Buy/Sell": "SELL",
                        "Open/CloseIndicator": "O",
                        "Quantity": "1",
                        "Proceeds": "500",
                        "NetCash": "500",
                        "IBCommission": "-1.5",
                        "FifoPnlRealized": "0",
                        "ClientAccountID": "U123",
                        "Description": "Test",
                        "Expiry": "20250321",
                    }
                )

            rows, files = read_csv_files(Path(tmpdir))
            assert len(rows) == 1
            assert len(files) == 1
            assert rows[0]["UnderlyingSymbol"] == "AAPL"

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows, files = read_csv_files(Path(tmpdir))
            assert rows == []
            assert files == []

    def test_skips_invalid_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "bad.csv"
            with open(csv_path, "w") as f:
                f.write("col1,col2\nval1,val2\n")

            rows, files = read_csv_files(Path(tmpdir))
            assert rows == []
            assert files == []


class TestGenerateMarkdown:
    """Tests for markdown report generation."""

    def test_generates_report(self):
        consolidated = [
            {
                "UnderlyingSymbol": "AAPL",
                "Symbol": "AAPL250321C200",
                "TradeDate": "20250101",
                "Strike": "200",
                "Put/Call": "C",
                "Buy/Sell": "SELL",
                "Open/CloseIndicator": "O",
                "Position": "SHORT",
                "Quantity": 1.0,
                "Proceeds": 500.0,
                "NetCash": 500.0,
                "IBCommission": -1.5,
                "FifoPnlRealized": 0.0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.md"
            generate_markdown(consolidated, {}, [], output)
            content = output.read_text()
            assert "Consolidated Trades Report" in content
            assert "AAPL" in content

    def test_with_unrealized_pnl(self):
        consolidated = [
            {
                "UnderlyingSymbol": "AAPL",
                "Symbol": "AAPL250321C200",
                "TradeDate": "20250101",
                "Strike": "200",
                "Put/Call": "C",
                "Buy/Sell": "SELL",
                "Open/CloseIndicator": "O",
                "Position": "SHORT",
                "Quantity": 1.0,
                "Proceeds": 500.0,
                "NetCash": 500.0,
                "IBCommission": -1.5,
                "FifoPnlRealized": 0.0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.md"
            generate_markdown(consolidated, {"AAPL": 150.0}, [], output)
            content = output.read_text()
            assert "Connected to IB" in content


class TestGenerateCsv:
    """Tests for CSV report generation."""

    def test_generates_csv(self):
        consolidated = [
            {
                "UnderlyingSymbol": "AAPL",
                "Symbol": "AAPL250321C200",
                "TradeDate": "20250101",
                "Strike": "200",
                "Put/Call": "C",
                "Buy/Sell": "SELL",
                "Open/CloseIndicator": "O",
                "Position": "SHORT",
                "Quantity": 1.0,
                "Proceeds": 500.0,
                "NetCash": 500.0,
                "IBCommission": -1.5,
                "FifoPnlRealized": 0.0,
                "ClientAccountID": "U123",
                "Description": "Test",
                "Expiry": "20250321",
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.csv"
            generate_csv(consolidated, output)
            assert output.exists()
            content = output.read_text()
            assert "AAPL" in content

    def test_empty_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.csv"
            generate_csv([], output)
            assert not output.exists()

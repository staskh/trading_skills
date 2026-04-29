# ABOUTME: Tests for insider trading module using real Yahoo Finance data.
# ABOUTME: Validates transaction retrieval, field structure, and multi-symbol support.

from trading_skills.insider_trading import (
    get_insider_transactions,
    get_multiple_insider_transactions,
)


class TestGetInsiderTransactions:
    def test_valid_symbol_structure(self):
        result = get_insider_transactions("AAPL")
        assert result["symbol"] == "AAPL"
        assert "transactions" in result
        assert "summary" in result
        assert "days_back" in result

    def test_transaction_fields(self):
        result = get_insider_transactions("AAPL")
        if result["transactions"]:
            tx = result["transactions"][0]
            assert "insider" in tx
            assert "role" in tx
            assert "transaction" in tx
            assert "transaction_type" in tx
            assert "shares" in tx
            assert "date" in tx
            assert "ownership" in tx
            assert tx["transaction_type"] in ("buy", "sell", "exercise", "other")

    def test_summary_fields(self):
        result = get_insider_transactions("AAPL")
        summary = result["summary"]
        assert "net_sentiment" in summary
        assert summary["net_sentiment"] in ("net_buying", "net_selling", "neutral")
        assert "buy_count" in summary
        assert "sell_count" in summary
        assert "buy_value" in summary
        assert "sell_value" in summary
        assert "net_value" in summary

    def test_days_back_filter(self):
        result_90 = get_insider_transactions("AAPL", days_back=90)
        result_7 = get_insider_transactions("AAPL", days_back=7)
        # 7-day window should have fewer or equal transactions
        assert result_7["count"] <= result_90["count"]

    def test_count_matches_transactions(self):
        result = get_insider_transactions("AAPL")
        assert result["count"] == len(result["transactions"])

    def test_invalid_symbol_returns_gracefully(self):
        result = get_insider_transactions("INVALIDXYZ999")
        assert "symbol" in result
        assert "transactions" in result or "error" in result


class TestGetMultipleInsiderTransactions:
    def test_multi_symbol_structure(self):
        result = get_multiple_insider_transactions(["AAPL", "MSFT"])
        assert "symbols" in result
        assert "results" in result
        assert len(result["results"]) == 2

    def test_results_have_symbol_keys(self):
        result = get_multiple_insider_transactions(["AAPL", "MSFT"])
        symbols_returned = {r["symbol"] for r in result["results"]}
        assert symbols_returned == {"AAPL", "MSFT"}

    def test_ranked_by_net_value(self):
        result = get_multiple_insider_transactions(["AAPL", "MSFT", "NVDA"])
        net_values = [r["summary"]["net_value"] for r in result["results"]]
        assert net_values == sorted(net_values, reverse=True)

# ABOUTME: Tests for stock report module.
# ABOUTME: Unit tests for compute_recommendation, analyze_spreads with mocked yfinance.

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd

from trading_skills.report import analyze_spreads, compute_recommendation, fetch_data

MODULE = "trading_skills.report"


class TestComputeRecommendation:
    """Unit tests for recommendation logic (no API calls)."""

    def test_strong_bullish(self):
        data = {
            "bullish": {"score": 7.0, "rsi": 55, "adx": 30},
            "pmcc": {"pmcc_score": 10, "iv_pct": 35},
            "fundamentals": {
                "info": {
                    "forwardPE": 12,
                    "returnOnEquity": 0.25,
                    "dividendYield": 3.0,
                    "debtToEquity": 50,
                    "revenueGrowth": 0.15,
                    "payoutRatio": 0.4,
                }
            },
            "piotroski": {"score": 8},
        }
        result = compute_recommendation(data)
        assert result["recommendation_level"] == "positive"
        assert len(result["strengths"]) > 0

    def test_bearish(self):
        data = {
            "bullish": {"score": 1.5, "rsi": 75, "adx": 15},
            "pmcc": {"pmcc_score": 3, "iv_pct": 70},
            "fundamentals": {
                "info": {
                    "forwardPE": 45,
                    "returnOnEquity": 0.05,
                    "dividendYield": 0,
                    "debtToEquity": 150,
                    "revenueGrowth": -0.10,
                    "payoutRatio": 0.9,
                }
            },
            "piotroski": {"score": 2},
        }
        result = compute_recommendation(data)
        assert result["recommendation_level"] in ["neutral", "negative"]
        assert len(result["risks"]) > 0

    def test_neutral(self):
        data = {
            "bullish": {"score": 4.0, "rsi": 50, "adx": 20},
            "pmcc": {"pmcc_score": 6, "iv_pct": 40},
            "fundamentals": {"info": {"forwardPE": 20}},
            "piotroski": {"score": 7},
        }
        result = compute_recommendation(data)
        assert result["recommendation_level"] == "neutral"

    def test_empty_data(self):
        result = compute_recommendation({})
        assert "recommendation_level" in result
        assert result["recommendation_level"] in ["positive", "neutral", "negative"]

    def test_result_fields(self):
        data = {
            "bullish": {"score": 5.0, "rsi": 55, "adx": 25},
            "pmcc": {"pmcc_score": 7, "iv_pct": 35},
            "fundamentals": {"info": {"forwardPE": 15}},
            "piotroski": {"score": 7},
        }
        result = compute_recommendation(data)
        assert "recommendation" in result
        assert "recommendation_level" in result
        assert "points" in result
        assert "strengths" in result
        assert "risks" in result

    def test_overbought_rsi_risk(self):
        data = {
            "bullish": {"score": 5.0, "rsi": 75, "adx": 20},
            "pmcc": {},
            "fundamentals": {"info": {}},
            "piotroski": {},
        }
        result = compute_recommendation(data)
        risks = " ".join(result["risks"])
        assert "overbought" in risks.lower()

    def test_high_debt_risk(self):
        data = {
            "bullish": {"score": 5.0, "rsi": 50, "adx": 20},
            "pmcc": {},
            "fundamentals": {"info": {"debtToEquity": 200}},
            "piotroski": {},
        }
        result = compute_recommendation(data)
        risks = " ".join(result["risks"])
        assert "debt" in risks.lower()


class TestAnalyzeSpreads:
    """Tests for spread strategy analysis with mocked yfinance."""

    def _mock_chain(self, price, strikes):
        """Create mock option chain data."""
        calls_data = []
        puts_data = []
        for s in strikes:
            call_mid = (
                max(0.5, (price - s) + 5) if s <= price + 20 else max(0.5, 10 - (s - price) * 0.2)
            )
            put_mid = (
                max(0.5, (s - price) + 5) if s >= price - 20 else max(0.5, 10 - (price - s) * 0.2)
            )
            calls_data.append(
                {
                    "strike": s,
                    "bid": call_mid - 0.25,
                    "ask": call_mid + 0.25,
                    "impliedVolatility": 0.35,
                    "openInterest": 100,
                    "volume": 50,
                }
            )
            puts_data.append(
                {
                    "strike": s,
                    "bid": put_mid - 0.25,
                    "ask": put_mid + 0.25,
                    "impliedVolatility": 0.35,
                    "openInterest": 100,
                    "volume": 50,
                }
            )

        chain = MagicMock()
        chain.calls = pd.DataFrame(calls_data)
        chain.puts = pd.DataFrame(puts_data)
        return chain

    @patch(f"{MODULE}.yf.Ticker")
    def test_returns_strategies(self, mock_ticker):
        price = 150.0
        strikes = [140, 145, 150, 155, 160]
        future = (datetime.now() + timedelta(days=40)).strftime("%Y-%m-%d")

        mock_instance = MagicMock()
        mock_instance.info = {"currentPrice": price}
        mock_instance.options = [future]
        mock_instance.option_chain.return_value = self._mock_chain(price, strikes)
        mock_ticker.return_value = mock_instance

        result = analyze_spreads("AAPL")
        assert "strategies" in result
        assert "expiry" in result
        assert result["underlying_price"] == price

    @patch(f"{MODULE}.yf.Ticker")
    def test_bull_call_spread(self, mock_ticker):
        price = 150.0
        strikes = [140, 145, 150, 155, 160]
        future = (datetime.now() + timedelta(days=40)).strftime("%Y-%m-%d")

        mock_instance = MagicMock()
        mock_instance.info = {"currentPrice": price}
        mock_instance.options = [future]
        mock_instance.option_chain.return_value = self._mock_chain(price, strikes)
        mock_ticker.return_value = mock_instance

        result = analyze_spreads("AAPL")
        assert "bull_call_spread" in result["strategies"]
        bcs = result["strategies"]["bull_call_spread"]
        assert bcs["direction"] == "bullish"
        assert bcs["long_strike"] < bcs["short_strike"]

    @patch(f"{MODULE}.yf.Ticker")
    def test_iron_condor(self, mock_ticker):
        price = 150.0
        strikes = [140, 145, 150, 155, 160]
        future = (datetime.now() + timedelta(days=40)).strftime("%Y-%m-%d")

        mock_instance = MagicMock()
        mock_instance.info = {"currentPrice": price}
        mock_instance.options = [future]
        mock_instance.option_chain.return_value = self._mock_chain(price, strikes)
        mock_ticker.return_value = mock_instance

        result = analyze_spreads("AAPL")
        assert "iron_condor" in result["strategies"]
        ic = result["strategies"]["iron_condor"]
        assert ic["put_long"] < ic["put_short"] < ic["call_short"] < ic["call_long"]

    @patch(f"{MODULE}.yf.Ticker")
    def test_no_price(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {}
        mock_ticker.return_value = mock_instance

        result = analyze_spreads("INVALID")
        assert "error" in result

    @patch(f"{MODULE}.yf.Ticker")
    def test_no_options(self, mock_ticker):
        mock_instance = MagicMock()
        mock_instance.info = {"currentPrice": 150.0}
        mock_instance.options = []
        mock_ticker.return_value = mock_instance

        result = analyze_spreads("AAPL")
        assert "error" in result

    @patch(f"{MODULE}.yf.Ticker")
    def test_exception_returns_error(self, mock_ticker):
        mock_ticker.side_effect = Exception("API Error")
        result = analyze_spreads("AAPL")
        assert "error" in result


class TestFetchData:
    """Tests for fetch_data with mocked dependencies."""

    @patch(f"{MODULE}.analyze_spreads")
    @patch(f"{MODULE}.calculate_piotroski_score")
    @patch(f"{MODULE}.get_fundamentals")
    @patch(f"{MODULE}.analyze_pmcc")
    @patch(f"{MODULE}.compute_bullish_score")
    def test_returns_all_sections(self, mock_bullish, mock_pmcc, mock_fund, mock_pio, mock_spreads):
        mock_bullish.return_value = {"score": 5.0}
        mock_pmcc.return_value = {"pmcc_score": 7}
        mock_fund.return_value = {"info": {"forwardPE": 15}}
        mock_pio.return_value = {"score": 7}
        mock_spreads.return_value = {"strategies": {}}

        result = fetch_data("AAPL")
        assert result["symbol"] == "AAPL"
        assert "bullish" in result
        assert "pmcc" in result
        assert "fundamentals" in result
        assert "piotroski" in result
        assert "spreads" in result

    @patch(f"{MODULE}.analyze_spreads")
    @patch(f"{MODULE}.calculate_piotroski_score")
    @patch(f"{MODULE}.get_fundamentals")
    @patch(f"{MODULE}.analyze_pmcc")
    @patch(f"{MODULE}.compute_bullish_score")
    def test_handles_none_returns(self, mock_bullish, mock_pmcc, mock_fund, mock_pio, mock_spreads):
        mock_bullish.return_value = None
        mock_pmcc.return_value = None
        mock_fund.return_value = {}
        mock_pio.return_value = {}
        mock_spreads.return_value = {}

        result = fetch_data("INVALID")
        assert result["bullish"] == {}
        assert result["pmcc"] == {}

# ABOUTME: Tests for sector ETF lookup and sector trend classification on constructed dicts.
# ABOUTME: No network access; inputs mirror compute_indicators results.

from trading_skills.sectors import classify_sector_trend, sector_etf


def ind(price, sma50, sma200, ret3m=None, macd=None, symbol=None):
    result = {
        "price": {"current": price},
        "indicators": {
            "sma200": {"sma50": sma50, "sma200": sma200},
            "structure": {"return_3m_pct": ret3m, "macd_hist": macd},
        },
    }
    if symbol:
        result["symbol"] = symbol
    return result


class TestSectorEtf:
    def test_sector(self):
        assert sector_etf("Technology", None) == "XLK"
        assert sector_etf("Real Estate", None) == "XLRE"

    def test_industry_first(self):
        assert sector_etf("Technology", "Semiconductors") == "SMH"

    def test_unknown_industry_falls_back_to_sector(self):
        assert sector_etf("Energy", "Oil & Gas Midstream") == "XLE"

    def test_none(self):
        assert sector_etf(None, None) is None
        assert sector_etf("Nope", "Nope") is None


class TestClassifySectorTrend:
    spy = ind(500, 490, 450, ret3m=4.0)

    def test_bullish(self):
        r = classify_sector_trend(
            ind(100, 95, 90, ret3m=10.0),
            ind(60, 55, 50, ret3m=6.0, symbol="XLK"),
            self.spy,
        )
        assert r == {
            "etf": "XLK",
            "trend": "bullish",
            "symbol_vs_etf_3m_pct": 4.0,
            "etf_vs_spy_3m_pct": 2.0,
            "symbol_weaker": False,
        }

    def test_bearish_below_sma200(self):
        r = classify_sector_trend(
            ind(100, 95, 90, ret3m=-5.0), ind(40, 55, 50, ret3m=1.0, macd=1), self.spy
        )
        assert r["trend"] == "bearish"
        assert r["symbol_weaker"] is True

    def test_bearish_negative_macd(self):
        r = classify_sector_trend(ind(100, 95, 90), ind(52, 55, 50, ret3m=1.0, macd=-0.1), self.spy)
        assert r["trend"] == "bearish"

    def test_neutral(self):
        r = classify_sector_trend(ind(100, 95, 90), ind(52, 55, 50, ret3m=1.0, macd=0.2), self.spy)
        assert r["trend"] == "neutral"

    def test_missing_values_give_none(self):
        r = classify_sector_trend(ind(100, 95, 90), {"error": "x"}, {"error": "y"})
        assert r == {
            "etf": None,
            "trend": None,
            "symbol_vs_etf_3m_pct": None,
            "etf_vs_spy_3m_pct": None,
            "symbol_weaker": None,
        }

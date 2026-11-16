# ABOUTME: Sector and industry ETF map and sector trend classification relative to the ETF and SPY.
# ABOUTME: classify_sector_trend is pure and works on compute_indicators results.

from trading_skills.market import _price, _sma

SECTOR_ETF = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

INDUSTRY_ETF = {
    "Semiconductors": "SMH",
    "Biotechnology": "XBI",
    "Banks - Regional": "KRE",
    "Airlines": "JETS",
    "Oil & Gas E&P": "XOP",
}


def sector_etf(sector: str | None, industry: str | None) -> str | None:
    """Return the ETF for the industry if mapped, else for the sector, else None."""
    return INDUSTRY_ETF.get(industry) or SECTOR_ETF.get(sector)


def _structure(result: dict, name: str) -> float | None:
    return ((result.get("indicators") or {}).get("structure") or {}).get(name)


def _diff(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else round(left - right, 2)


def _trend(etf: dict) -> str | None:
    price, sma50, sma200 = _price(etf), _sma(etf, "sma50"), _sma(etf, "sma200")
    if price is None or sma50 is None or sma200 is None:
        return None
    macd_hist = _structure(etf, "macd_hist")
    if price < sma50 and (price < sma200 or (macd_hist is not None and macd_hist < 0)):
        return "bearish"
    if price > sma50 > sma200:
        return "bullish"
    return "neutral"


def classify_sector_trend(symbol_ind: dict, etf_ind: dict, spy_ind: dict) -> dict:
    """Classify the sector ETF trend and the symbol's 3-month return relative to ETF and SPY.

    bearish: ETF < SMA50 and (ETF < SMA200 or MACD hist < 0).
    bullish: ETF > SMA50 > SMA200. Otherwise neutral.
    Any missing input leaves the dependent output None.
    """
    symbol_3m = _structure(symbol_ind, "return_3m_pct")
    etf_3m = _structure(etf_ind, "return_3m_pct")
    spy_3m = _structure(spy_ind, "return_3m_pct")
    symbol_vs_etf = _diff(symbol_3m, etf_3m)
    return {
        "etf": etf_ind.get("symbol"),
        "trend": _trend(etf_ind),
        "symbol_vs_etf_3m_pct": symbol_vs_etf,
        "etf_vs_spy_3m_pct": _diff(etf_3m, spy_3m),
        "symbol_weaker": None if symbol_vs_etf is None else symbol_vs_etf < 0,
    }

# ABOUTME: Unit tests for futures classification + FOP greeks/quote extraction (pure, no IB).
# ABOUTME: Covers is_futures/futures_exchange and options._extract_greeks/_quote_row.

from types import SimpleNamespace

from trading_skills.broker.futures import (
    FUTURES_SYMBOLS,
    futures_exchange,
    futures_underlying,
    is_futures,
)
from trading_skills.broker.options import _extract_greeks, _quote_row


class TestIsFutures:
    def test_known_futures_true(self):
        for s in ("NQ", "ES", "CL", "GC", "ZB", "MNQ"):
            assert is_futures(s)

    def test_case_insensitive(self):
        assert is_futures("nq")

    def test_equities_and_etfs_false(self):
        for s in ("AAPL", "SPY", "QQQ", "MSFT", "IWM"):
            assert not is_futures(s)


class TestFuturesExchange:
    def test_correct_exchange_per_root(self):
        assert futures_exchange("NQ") == "CME"
        assert futures_exchange("ES") == "CME"
        assert futures_exchange("CL") == "NYMEX"
        assert futures_exchange("NG") == "NYMEX"
        assert futures_exchange("GC") == "COMEX"
        assert futures_exchange("SI") == "COMEX"
        assert futures_exchange("ZB") == "CBOT"
        assert futures_exchange("YM") == "CBOT"

    def test_unknown_defaults_cme(self):
        assert futures_exchange("ZZZ") == "CME"

    def test_underlying_uses_exchange(self):
        c = futures_underlying("CL")
        assert c.symbol == "CL"
        assert c.exchange == "NYMEX"

    def test_all_symbols_have_exchange(self):
        for s in FUTURES_SYMBOLS:
            assert futures_exchange(s) in {"CME", "CBOT", "NYMEX", "COMEX"}


class TestExtractGreeks:
    def test_none_returns_none(self):
        assert _extract_greeks(None) is None

    def test_all_none_greeks_returns_none(self):
        mg = SimpleNamespace(delta=None, gamma=None, theta=None, vega=None, impliedVol=None)
        assert _extract_greeks(mg) is None

    def test_populated_greeks(self):
        mg = SimpleNamespace(
            delta=0.55123, gamma=0.0123, theta=-0.4567, vega=0.234, impliedVol=0.3251
        )
        g = _extract_greeks(mg)
        assert g["delta"] == 0.5512
        assert g["theta"] == -0.4567
        assert g["iv"] == 32.51  # impliedVol * 100

    def test_nan_iv_handled(self):
        mg = SimpleNamespace(delta=0.5, gamma=0.0, theta=0.0, vega=0.0, impliedVol=float("nan"))
        g = _extract_greeks(mg)
        assert g["iv"] is None
        assert g["delta"] == 0.5


class TestQuoteRow:
    def _ticker(self, strike, mult="20", with_greeks=True):
        mg = (
            SimpleNamespace(delta=0.4, gamma=0.01, theta=-0.2, vega=0.1, impliedVol=0.25)
            if with_greeks
            else None
        )
        contract = SimpleNamespace(strike=strike, multiplier=mult)
        return SimpleNamespace(
            contract=contract, bid=10.0, ask=11.0, last=10.5, volume=123, modelGreeks=mg
        )

    def test_fop_row_includes_multiplier_and_greeks(self):
        row = _quote_row(self._ticker(31300.0), "C", 30000.0, include_multiplier=True)
        assert row["multiplier"] == 20
        assert row["greeks"]["delta"] == 0.4
        assert row["impliedVolatility"] == 25.0
        assert row["inTheMoney"] is False  # call, strike > underlying

    def test_equity_row_no_multiplier_key(self):
        row = _quote_row(self._ticker(550.0, mult=None), "P", 500.0, include_multiplier=False)
        assert "multiplier" not in row
        assert row["inTheMoney"] is True  # put, strike > underlying
        assert row["bid"] == 10.0

    def test_missing_underlying_price_itm_none(self):
        row = _quote_row(self._ticker(450.0), "C", None, include_multiplier=True)
        assert row["inTheMoney"] is None

# ABOUTME: Tests for the centralized futures symbol registry.
# ABOUTME: Validates exchange mappings, is_futures helper, and Yahoo ticker conversion.

import pytest

from trading_skills.broker.futures import FUTURES_EXCHANGE, futures_yahoo_ticker


class TestFuturesExchange:
    def test_cme_symbols(self):
        for sym in ("NQ", "ES", "RTY", "6E", "6J", "6B"):
            assert FUTURES_EXCHANGE[sym] == "CME", sym

    def test_cbot_symbols(self):
        for sym in ("YM", "ZB", "ZN", "ZF", "ZT"):
            assert FUTURES_EXCHANGE[sym] == "CBOT", sym

    def test_nymex_symbols(self):
        assert FUTURES_EXCHANGE["CL"] == "NYMEX"

    def test_comex_symbols(self):
        for sym in ("GC", "SI"):
            assert FUTURES_EXCHANGE[sym] == "COMEX", sym


class TestFuturesYahooTicker:
    def test_appends_suffix(self):
        assert futures_yahoo_ticker("NQ") == "NQ=F"
        assert futures_yahoo_ticker("ES") == "ES=F"
        assert futures_yahoo_ticker("YM") == "YM=F"

    def test_no_double_suffix(self):
        assert futures_yahoo_ticker("NQ=F") == "NQ=F"

    def test_any_symbol_gets_suffix(self):
        assert futures_yahoo_ticker("AAPL") == "AAPL=F"

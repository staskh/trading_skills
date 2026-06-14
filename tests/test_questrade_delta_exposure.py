# ABOUTME: Tests for Questrade delta-exposure Questrade->Yahoo symbol mapping.
# ABOUTME: Covers share-class tickers (e.g. BTCX.B.TO) and plain TICKER.EXCHANGE symbols.

from questrade_skills.delta_exposure import _to_yahoo_symbol


class TestToYahooSymbol:
    def test_share_class_ticker_uses_hyphen(self):
        assert _to_yahoo_symbol("BTCX.B.TO") == "BTCX-B.TO"

    def test_another_share_class_ticker(self):
        assert _to_yahoo_symbol("RCI.B.TO") == "RCI-B.TO"

    def test_plain_exchange_ticker_unchanged(self):
        assert _to_yahoo_symbol("XEQT.TO") == "XEQT.TO"

    def test_plain_us_ticker_unchanged(self):
        assert _to_yahoo_symbol("AAPL") == "AAPL"

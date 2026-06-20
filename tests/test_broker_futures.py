# ABOUTME: Unit tests for FOP exchange selection + greeks/quote extraction (pure, no IB).
# ABOUTME: Covers futures._pick_future_exchange, resolve_fop_contracts, and options helpers.

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_skills.broker.futures import _pick_future_exchange, resolve_fop_contracts
from trading_skills.broker.options import _extract_greeks, _quote_row


def _fut(expiry, exchange):
    return SimpleNamespace(lastTradeDateOrContractMonth=expiry, exchange=exchange)


class TestPickFutureExchange:
    def test_picks_nearest_expiry_exchange(self):
        contracts = [_fut("20260919", "CME"), _fut("20260618", "CME"), _fut("20261218", "CME")]
        assert _pick_future_exchange(contracts) == "CME"

    def test_respects_actual_exchange_value(self):
        # Whatever IB reports is returned verbatim (no hardcoded assumption).
        assert _pick_future_exchange([_fut("20260720", "NYMEX")]) == "NYMEX"
        assert _pick_future_exchange([_fut("20260828", "COMEX")]) == "COMEX"

    def test_empty_returns_none(self):
        assert _pick_future_exchange([]) is None

    def test_contracts_without_expiry_or_exchange_ignored(self):
        contracts = [
            None,
            SimpleNamespace(lastTradeDateOrContractMonth="", exchange="CME"),
            SimpleNamespace(lastTradeDateOrContractMonth="20260618", exchange=None),
        ]
        assert _pick_future_exchange(contracts) is None

    def test_mixed_valid_and_invalid(self):
        contracts = [None, _fut("20260618", "CBOT"), SimpleNamespace()]
        assert _pick_future_exchange(contracts) == "CBOT"


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


def _fop_detail(trading_class: str, con_id: int):
    """Build a mock ContractDetails whose .contract has a tradingClass + conId."""
    contract = MagicMock()
    contract.tradingClass = trading_class
    contract.conId = con_id
    detail = MagicMock()
    detail.contract = contract
    return detail


class TestResolveFopContracts:
    """resolve_fop_contracts must disambiguate FOP tradingClass collisions."""

    @pytest.mark.asyncio
    async def test_prefers_standard_monthly_class(self):
        # Same (expiry, strike) returns both the standard NQ class and a Q3D weekly.
        ib = MagicMock()
        ib.reqContractDetailsAsync = AsyncMock(
            return_value=[_fop_detail("Q3D", 888), _fop_detail("NQ", 877)]
        )
        resolved = await resolve_fop_contracts(ib, "NQ", "20260618", [21000], "C", "CME")
        assert len(resolved) == 1
        assert resolved[0].tradingClass == "NQ"
        assert resolved[0].conId == 877

    @pytest.mark.asyncio
    async def test_falls_back_when_no_standard_class(self):
        ib = MagicMock()
        ib.reqContractDetailsAsync = AsyncMock(return_value=[_fop_detail("Q2D", 555)])
        resolved = await resolve_fop_contracts(ib, "NQ", "20260611", [21000], "C", "CME")
        assert len(resolved) == 1
        assert resolved[0].conId == 555

    @pytest.mark.asyncio
    async def test_skips_strike_with_no_contracts(self):
        ib = MagicMock()
        ib.reqContractDetailsAsync = AsyncMock(return_value=[])
        resolved = await resolve_fop_contracts(ib, "NQ", "20260618", [21000, 21100], "C", "CME")
        assert resolved == []

    @pytest.mark.asyncio
    async def test_multiple_strikes_resolved(self):
        details_by_call = [
            [_fop_detail("NQ", 100)],
            [_fop_detail("NQ", 101)],
        ]
        ib = MagicMock()
        ib.reqContractDetailsAsync = AsyncMock(side_effect=details_by_call)
        resolved = await resolve_fop_contracts(ib, "NQ", "20260618", [21000, 21100], "C", "CME")
        assert len(resolved) == 2
        assert resolved[0].conId == 100
        assert resolved[1].conId == 101

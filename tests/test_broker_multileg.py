# ABOUTME: Tests for the IB multi-leg data layer helpers; live test marked manual.
# ABOUTME: Live test requires TWS or IB Gateway running locally on port 7496.

import asyncio
from datetime import date, timedelta

import pytest

from trading_skills.broker.multileg import (
    _dte_window,
    _strike_window,
    load_config,
    pick_expiry,
    propose_trades,
    underlying_contract,
)


def _exp(days):
    return (date.today() + timedelta(days=days)).strftime("%Y%m%d")


def test_pick_expiry_nearest_to_target():
    exps = [_exp(d) for d in (3, 10, 17, 31)]
    assert pick_expiry(exps, 14) in (exps[1], exps[2])
    assert pick_expiry(exps, 30) == exps[3]


def test_pick_expiry_skips_expired():
    assert pick_expiry([_exp(-1)], 1) is None


def test_strike_window_caps_and_centers():
    strikes = [float(k) for k in range(4000, 6000, 5)]
    sel = _strike_window(strikes, 5000, 0.2, 30 / 365, 50)
    assert len(sel) == 50
    assert min(sel) < 5000 < max(sel)


def test_dte_window_variants():
    cfg = load_config()
    assert _dte_window(cfg["strategies"]["iron_duck"]) == (1, 21)
    assert _dte_window(cfg["strategies"]["time_fly"]) == (7, 21)
    assert _dte_window(cfg["strategies"]["dn_fly"]) == (7, 21)


def test_index_vs_stock_contract():
    assert underlying_contract("SPX").secType == "IND"
    assert underlying_contract("AAPL").secType == "STK"


@pytest.mark.manual
def test_live_spy_proposal():
    result = asyncio.run(propose_trades("SPY", strategies=["iron_duck", "dn_fly"]))
    assert result["success"] is True, result
    assert result["candidates"]

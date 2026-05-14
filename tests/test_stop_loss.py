# ABOUTME: Unit tests for stop-loss analytics and data-layer functions.
# ABOUTME: Analytics tests run without IBKR; data-layer tests use MagicMock.

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_skills.broker.stop_loss import (
    _cancel_orphan_orders,
    _execute_position_stop,
    _fetch_open_orders,
    _parse_existing_stops,
    _place_combo_stop_order,
    _place_simple_stop_order,
    build_position_analysis,
    calc_short_premium_decay_pct,
    calc_stop_basis,
    calc_stop_price,
    detect_orphan_orders,
    filter_orders_by_account,
    get_stop_loss_data,
    identify_positions,
    summarize_all_conditional_orders,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _opt(symbol, quantity, avg_cost, strike, expiry, right="C", account="U123"):
    return {
        "account": account,
        "symbol": symbol,
        "sec_type": "OPT",
        "quantity": quantity,
        "avg_cost": avg_cost,
        "strike": strike,
        "expiry": expiry,
        "right": right,
    }


def _stk(symbol, quantity=100, avg_cost=150.0, account="U123"):
    return {
        "account": account,
        "symbol": symbol,
        "sec_type": "STK",
        "quantity": quantity,
        "avg_cost": avg_cost,
        "strike": None,
        "expiry": None,
        "right": None,
    }


# ---------------------------------------------------------------------------
# calc_stop_basis
# ---------------------------------------------------------------------------


def test_stop_basis_normal_uses_market_when_higher():
    assert calc_stop_basis(40.0, 30.0, forced=False) == pytest.approx(40.0)


def test_stop_basis_normal_uses_avg_cost_when_market_lower():
    assert calc_stop_basis(25.0, 35.0, forced=False) == pytest.approx(35.0)


def test_stop_basis_normal_falls_back_to_avg_cost_when_no_market():
    assert calc_stop_basis(None, 35.0, forced=False) == pytest.approx(35.0)


def test_stop_basis_normal_falls_back_when_market_zero():
    assert calc_stop_basis(0.0, 35.0, forced=False) == pytest.approx(35.0)


def test_stop_basis_forced_uses_current_price():
    assert calc_stop_basis(25.0, 35.0, forced=True) == pytest.approx(25.0)


def test_stop_basis_forced_falls_back_to_avg_cost_when_no_market():
    assert calc_stop_basis(None, 35.0, forced=True) == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# calc_stop_price
# ---------------------------------------------------------------------------


def test_stop_price_50pct_normal():
    # basis = max(40, 30) = 40; stop = 40 * 0.5 = 20
    assert calc_stop_price(40.0, 30.0, stop_pct=50.0) == pytest.approx(20.0)


def test_stop_price_50pct_forced():
    # basis = current_mid = 25; stop = 25 * 0.5 = 12.5
    assert calc_stop_price(25.0, 35.0, stop_pct=50.0, forced=True) == pytest.approx(12.5)


def test_stop_price_custom_pct():
    # basis = 40; stop = 40 * 0.75 = 30
    assert calc_stop_price(40.0, 30.0, stop_pct=25.0) == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# calc_short_premium_decay_pct
# ---------------------------------------------------------------------------


def test_short_decay_pct_fully_intact():
    assert calc_short_premium_decay_pct(5.0, 5.0) == pytest.approx(0.0)


def test_short_decay_pct_fully_captured():
    assert calc_short_premium_decay_pct(5.0, 0.0) == pytest.approx(100.0)


def test_short_decay_pct_90pct():
    assert calc_short_premium_decay_pct(5.0, 0.50) == pytest.approx(90.0)


def test_short_decay_pct_zero_premium():
    assert calc_short_premium_decay_pct(0.0, 1.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# identify_positions
# ---------------------------------------------------------------------------


def test_identify_pmcc_basic():
    normalized = [
        _opt("NVDA", 3, 44.27, 200.0, "20270115"),  # long LEAPS
        _opt("NVDA", -3, -0.61, 235.0, "20260515"),  # short
    ]
    result = identify_positions(normalized)
    assert len(result) == 1
    pos = result[0]
    assert pos["type"] == "pmcc"
    assert pos["symbol"] == "NVDA"
    assert pos["qty"] == 3
    assert pos["leaps"]["strike"] == 200.0
    assert len(pos["shorts"]) == 1
    assert pos["shorts"][0]["strike"] == 235.0


def test_identify_naked_leaps():
    normalized = [_opt("NVDA", 3, 44.27, 200.0, "20270115")]
    result = identify_positions(normalized)
    assert len(result) == 1
    assert result[0]["type"] == "leaps"
    assert result[0]["leaps"]["strike"] == 200.0


def test_identify_stock():
    normalized = [_stk("AAPL", quantity=100, avg_cost=175.0)]
    result = identify_positions(normalized)
    assert len(result) == 1
    assert result[0]["type"] == "stock"
    assert result[0]["symbol"] == "AAPL"
    assert result[0]["qty"] == 100
    assert result[0]["avg_cost"] == 175.0


def test_identify_multiple_shorts_same_symbol():
    normalized = [
        _opt("IWM", 15, 21.28, 260.0, "20260918"),  # long LEAPS
        _opt("IWM", -15, -5.0, 280.0, "20260618"),  # short 1
        _opt("IWM", -10, -3.0, 285.0, "20260718"),  # short 2
    ]
    result = identify_positions(normalized)
    assert len(result) == 1
    assert result[0]["type"] == "pmcc"
    assert len(result[0]["shorts"]) == 2


def test_identify_mixed_portfolio():
    normalized = [
        _opt("NVDA", 3, 44.27, 200.0, "20270115"),
        _opt("NVDA", -3, -0.61, 235.0, "20260515"),
        _opt("SOLO", 2, 10.0, 50.0, "20260918"),  # naked LEAPS
        _stk("AAPL"),
    ]
    result = identify_positions(normalized)
    types = {p["type"] for p in result}
    assert types == {"pmcc", "leaps", "stock"}


def test_identify_ignores_short_stock_positions():
    # Short stock (negative qty) should be ignored
    normalized = [_stk("AAPL", quantity=-100)]
    result = identify_positions(normalized)
    assert result == []


# ---------------------------------------------------------------------------
# build_position_analysis
# ---------------------------------------------------------------------------


def _pmcc_pos(
    symbol="NVDA",
    qty=3,
    leaps_cost=44.27,
    leaps_strike=200.0,
    leaps_expiry="20270115",
    short_cost=0.61,
    short_strike=235.0,
    short_expiry="20260515",
    account="U123",
):
    return {
        "type": "pmcc",
        "symbol": symbol,
        "account": account,
        "qty": qty,
        "leaps": {
            "strike": leaps_strike,
            "expiry": leaps_expiry,
            "right": "C",
            "avg_cost": leaps_cost,
        },
        "shorts": [
            {
                "strike": short_strike,
                "expiry": short_expiry,
                "right": "C",
                "premium_received": short_cost,
                "qty": qty,
            }
        ],
    }


def _leaps_pos(symbol="SOLO", qty=2, avg_cost=10.0, strike=50.0, expiry="20260918", account="U123"):
    return {
        "type": "leaps",
        "symbol": symbol,
        "account": account,
        "qty": qty,
        "leaps": {"strike": strike, "expiry": expiry, "right": "C", "avg_cost": avg_cost},
    }


def _stock_pos(symbol="AAPL", qty=100, avg_cost=175.0, account="U123"):
    return {"type": "stock", "symbol": symbol, "account": account, "qty": qty, "avg_cost": avg_cost}


def test_build_pmcc_no_alert():
    pos = _pmcc_pos()
    result = build_position_analysis(
        position=pos,
        underlying_price=219.05,
        current_mid=44.23,
        short_mids=[0.56],
        existing_stop=None,
        stop_pct=50.0,
        forced=False,
    )
    assert result["type"] == "pmcc"
    assert result["stop_loss"]["action"] == "place_new"
    assert result["alert_soon"] is False
    assert result["leaps"]["stop_basis"] == pytest.approx(44.27)  # max(44.23, 44.27)
    assert result["leaps"]["stop_price"] == pytest.approx(22.14)


def test_build_pmcc_alert_soon():
    # LEAPS down 46% from basis — past early_warning_pct (25%)
    pos = _pmcc_pos(leaps_cost=2.93)
    result = build_position_analysis(
        position=pos,
        underlying_price=26.12,
        current_mid=1.58,
        short_mids=[0.24],
        existing_stop=None,
        stop_pct=50.0,
        forced=False,
    )
    assert result["alert_soon"] is True
    types = [a["type"] for a in result["alerts"]]
    assert "leaps_early_warning" in types


def test_build_stock_analysis():
    pos = _stock_pos()
    result = build_position_analysis(
        position=pos,
        underlying_price=189.50,
        current_mid=189.50,
        short_mids=[],
        existing_stop=None,
        stop_pct=50.0,
        forced=False,
    )
    assert result["type"] == "stock"
    # basis = max(189.50, 175.0) = 189.50; stop = 189.50 * 0.5 = 94.75
    assert result["stock"]["stop_basis"] == pytest.approx(189.50)
    assert result["stop_loss"]["stop_price"] == pytest.approx(94.75)
    assert result["alert_soon"] is False


def test_build_preserve_existing_stop():
    pos = _pmcc_pos()
    result = build_position_analysis(
        position=pos,
        underlying_price=219.05,
        current_mid=44.23,
        short_mids=[0.56],
        existing_stop=25.0,  # existing stop is higher (more protective) than new ~22
        stop_pct=50.0,
        forced=False,
    )
    assert result["stop_loss"]["action"] == "preserve_existing"


def test_build_overwrite_with_forced():
    pos = _pmcc_pos()
    result = build_position_analysis(
        position=pos,
        underlying_price=219.05,
        current_mid=44.23,
        short_mids=[0.56],
        existing_stop=25.0,
        stop_pct=50.0,
        forced=True,
    )
    assert result["stop_loss"]["action"] == "overwrite"


def test_build_forced_uses_current_mid_as_basis():
    pos = _pmcc_pos(leaps_cost=44.27)
    result = build_position_analysis(
        position=pos,
        underlying_price=219.05,
        current_mid=30.0,  # lower than avg_cost
        short_mids=[0.56],
        existing_stop=None,
        stop_pct=50.0,
        forced=True,  # forced: basis = current_mid = 30.0
    )
    assert result["leaps"]["stop_basis"] == pytest.approx(30.0)
    assert result["stop_loss"]["stop_price"] == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# detect_orphan_orders
# ---------------------------------------------------------------------------


def _sl_order(order_ref, symbol="NVDA", order_id=1):
    return {
        "order_ref": order_ref,
        "symbol": symbol,
        "order_id": order_id,
        "conditions": [{"price": 20.0, "is_more": False}],
    }


def test_detect_orphan_no_orphans():
    positions = [_pmcc_pos()]  # NVDA 200.0 20270115
    orders = [_sl_order("SL_FALL_NVDA_200.0_20270115")]
    assert detect_orphan_orders(orders, positions) == []


def test_detect_orphan_detects_closed_position():
    positions = []
    orders = [_sl_order("SL_FALL_NVDA_200.0_20270115")]
    orphans = detect_orphan_orders(orders, positions)
    assert len(orphans) == 1
    assert orphans[0]["order_ref"] == "SL_FALL_NVDA_200.0_20270115"


def test_detect_orphan_ignores_non_sl_orders():
    positions = []
    orders = [_sl_order("MANUAL_ORDER")]
    assert detect_orphan_orders(orders, positions) == []


def test_detect_orphan_stock_position():
    positions = [_stock_pos()]  # AAPL stock
    orders = [
        _sl_order("SL_FALL_AAPL_STK", symbol="AAPL"),
        _sl_order("SL_FALL_NVDA_200.0_20270115", symbol="NVDA"),  # orphan
    ]
    orphans = detect_orphan_orders(orders, positions)
    assert len(orphans) == 1
    assert orphans[0]["order_ref"] == "SL_FALL_NVDA_200.0_20270115"


# ---------------------------------------------------------------------------
# filter_orders_by_account  (issue #37)
# ---------------------------------------------------------------------------


def _acct_order(order_ref, account, order_id=1):
    return {
        "order_ref": order_ref,
        "account": account,
        "order_id": order_id,
        "symbol": "X",
        "conditions": [{"price": 1.0, "is_more": False}],
    }


def test_filter_orders_by_account_single_account():
    orders = [
        _acct_order("SL_FALL_A", "U1", order_id=1),
        _acct_order("SL_FALL_B", "U2", order_id=2),
        _acct_order("SL_FALL_C", "U1", order_id=3),
    ]
    result = filter_orders_by_account(orders, ["U1"])
    assert [o["order_id"] for o in result] == [1, 3]


def test_filter_orders_by_account_multi_account():
    orders = [
        _acct_order("SL_FALL_A", "U1", order_id=1),
        _acct_order("SL_FALL_B", "U2", order_id=2),
        _acct_order("SL_FALL_C", "U3", order_id=3),
    ]
    result = filter_orders_by_account(orders, ["U1", "U2"])
    assert [o["order_id"] for o in result] == [1, 2]


def test_filter_orders_by_account_empty_accounts_drops_all():
    orders = [_acct_order("SL_FALL_A", "U1")]
    assert filter_orders_by_account(orders, []) == []


def test_filter_orders_by_account_drops_orders_without_account():
    orders = [
        _acct_order("SL_FALL_A", "U1", order_id=1),
        {"order_ref": "SL_FALL_B", "order_id": 2},  # no account field
        _acct_order("SL_FALL_C", "", order_id=3),  # empty account
    ]
    result = filter_orders_by_account(orders, ["U1"])
    assert [o["order_id"] for o in result] == [1]


def test_filter_then_detect_orphan_protects_other_accounts():
    """Regression for issue #37: scoping orphan detection to queried accounts must
    leave SL_ orders in other accounts untouched, even when the position list is
    empty for the queried account."""
    orders = [
        _acct_order("SL_FALL_NVDA_200.0_20270115", "U2", order_id=10),
        _acct_order("SL_FALL_AAPL_STK", "U1", order_id=11),
    ]
    # Querying U1 with no AAPL position would, before the fix, see both orders as
    # orphans because positions are scoped to U1 but orders weren't.
    positions_in_u1: list[dict] = []
    scoped = filter_orders_by_account(orders, ["U1"])
    orphans = detect_orphan_orders(scoped, positions_in_u1)
    # The U2 order must NOT be in the orphan list.
    assert all(o.get("account") != "U2" for o in orphans)
    # The U1 AAPL order with no matching position is still a correct orphan.
    assert [o["order_id"] for o in orphans] == [11]


# ---------------------------------------------------------------------------
# summarize_all_conditional_orders
# ---------------------------------------------------------------------------


def _cond_order(order_ref, conditions=None):
    return {
        "order_ref": order_ref,
        "conditions": conditions or [],
        "symbol": "NVDA",
        "order_id": 1,
        "action": "BUY",
        "qty": 1,
    }


def test_all_conditional_orders_splits_module_and_manual():
    orders = [
        _cond_order("SL_FALL_NVDA_200.0_20270115", [{"price": 22.0, "is_more": False}]),
        _cond_order("MANUAL_COND", [{"price": 200.0, "is_more": False}]),
    ]
    result = summarize_all_conditional_orders(orders)
    assert len(result["module"]) == 1
    assert len(result["manual"]) == 1


def test_all_conditional_orders_excludes_no_conditions():
    orders = [
        _cond_order("SL_FALL_NVDA_200.0_20270115", []),
        _cond_order("MANUAL_COND", []),
    ]
    result = summarize_all_conditional_orders(orders)
    assert result == {"module": [], "manual": []}


def test_all_conditional_orders_empty():
    assert summarize_all_conditional_orders([]) == {"module": [], "manual": []}


# ---------------------------------------------------------------------------
# identify_positions — extra coverage
# ---------------------------------------------------------------------------


def test_identify_pmcc_with_extra_naked_leaps():
    # Two long options + one short: longest dated = LEAPS (PMCC), other = naked LEAPS
    normalized = [
        _opt("NVDA", 3, 44.27, 200.0, "20270115"),  # longest → PMCC LEAPS
        _opt("NVDA", 2, 15.0, 210.0, "20260918"),  # shorter → naked LEAPS
        _opt("NVDA", -3, -0.61, 235.0, "20260515"),  # short for PMCC
    ]
    result = identify_positions(normalized)
    types = [p["type"] for p in result]
    assert types.count("pmcc") == 1
    assert types.count("leaps") == 1
    pmcc = next(p for p in result if p["type"] == "pmcc")
    assert pmcc["leaps"]["expiry"] == "20270115"


# ---------------------------------------------------------------------------
# build_position_analysis — alert coverage
# ---------------------------------------------------------------------------


def test_build_short_premium_decay_alert():
    # 95% of short premium captured → decay alert
    pos = _pmcc_pos(short_cost=1.0, short_strike=235.0)
    result = build_position_analysis(
        position=pos,
        underlying_price=219.05,
        current_mid=44.27,
        short_mids=[0.05],  # 95% decayed
        existing_stop=None,
        stop_pct=50.0,
        forced=False,
    )
    types = [a["type"] for a in result["alerts"]]
    assert "short_premium_decay" in types


def test_build_short_near_strike_alert():
    # Spot within 3% of short strike (threshold=5%)
    pos = _pmcc_pos(short_strike=220.0)
    result = build_position_analysis(
        position=pos,
        underlying_price=219.05,  # 0.4% below 220 strike
        current_mid=44.23,
        short_mids=[5.0],
        existing_stop=None,
        stop_pct=50.0,
        forced=False,
        short_near_strike_pct=5.0,
    )
    types = [a["type"] for a in result["alerts"]]
    assert "short_near_strike" in types


def test_build_existing_stop_lower_places_new():
    # Existing stop is lower (less protective) → place_new
    pos = _pmcc_pos()
    result = build_position_analysis(
        position=pos,
        underlying_price=219.05,
        current_mid=44.23,
        short_mids=[0.56],
        existing_stop=10.0,  # lower than computed ~22 → should place new
        stop_pct=50.0,
        forced=False,
    )
    assert result["stop_loss"]["action"] == "place_new"


# ---------------------------------------------------------------------------
# _parse_existing_stops (pure function)
# ---------------------------------------------------------------------------


class TestParseExistingStops:
    def test_extracts_stop_price_from_sl_fall_order(self):
        orders = [
            {
                "order_ref": "SL_FALL_NVDA_200.0_20270115",
                "conditions": [{"price": 22.0, "is_more": False}],
            }
        ]
        result = _parse_existing_stops(orders)
        assert result == {"NVDA_200.0_20270115": 22.0}

    def test_keeps_max_when_duplicate_keys(self):
        orders = [
            {
                "order_ref": "SL_FALL_NVDA_200.0_20270115",
                "conditions": [{"price": 20.0, "is_more": False}],
            },
            {
                "order_ref": "SL_FALL_NVDA_200.0_20270115",
                "conditions": [{"price": 25.0, "is_more": False}],
            },
        ]
        result = _parse_existing_stops(orders)
        assert result["NVDA_200.0_20270115"] == 25.0

    def test_ignores_non_sl_fall_orders(self):
        orders = [{"order_ref": "MANUAL_ORDER", "conditions": [{"price": 100.0, "is_more": False}]}]
        assert _parse_existing_stops(orders) == {}

    def test_ignores_orders_without_conditions(self):
        orders = [{"order_ref": "SL_FALL_NVDA_200.0_20270115", "conditions": []}]
        assert _parse_existing_stops(orders) == {}

    def test_empty_input(self):
        assert _parse_existing_stops([]) == {}


# ---------------------------------------------------------------------------
# _fetch_open_orders
# ---------------------------------------------------------------------------


class TestFetchOpenOrders:
    def _make_trade(self, order_ref, symbol, sec_type="OPT", order_id=1, conditions=None):
        trade = MagicMock()
        trade.contract.symbol = symbol
        trade.contract.secType = sec_type
        trade.contract.strike = 200.0
        trade.contract.lastTradeDateOrContractMonth = "20270115"
        trade.contract.right = "C"
        trade.order.orderId = order_id
        trade.order.orderRef = order_ref
        trade.order.action = "SELL"
        trade.order.orderType = "MKT"
        trade.order.totalQuantity = 3
        trade.order.conditions = conditions or []
        return trade

    def test_returns_normalized_orders(self):
        mock_ib = MagicMock()
        mock_ib.reqAllOpenOrdersAsync = AsyncMock(return_value=[])
        cond = MagicMock()
        cond.price = 22.0
        cond.isMore = False
        trade = self._make_trade("SL_FALL_NVDA_200.0_20270115", "NVDA", conditions=[cond])
        mock_ib.openTrades.return_value = [trade]

        _mock_timeout = AsyncMock(return_value=[])
        with patch("trading_skills.broker.stop_loss.fetch_with_timeout", new=_mock_timeout):
            result = asyncio.run(_fetch_open_orders(mock_ib))

        assert len(result) == 1
        assert result[0]["order_ref"] == "SL_FALL_NVDA_200.0_20270115"
        assert result[0]["symbol"] == "NVDA"
        assert result[0]["conditions"] == [{"price": 22.0, "is_more": False}]

    def test_returns_empty_when_no_trades(self):
        mock_ib = MagicMock()
        mock_ib.reqAllOpenOrdersAsync = AsyncMock(return_value=[])
        mock_ib.openTrades.return_value = []

        _mock_timeout = AsyncMock(return_value=[])
        with patch("trading_skills.broker.stop_loss.fetch_with_timeout", new=_mock_timeout):
            result = asyncio.run(_fetch_open_orders(mock_ib))

        assert result == []


# ---------------------------------------------------------------------------
# _cancel_orphan_orders
# ---------------------------------------------------------------------------


class TestCancelOrphanOrders:
    def test_cancels_matching_order(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 42
        mock_ib.openTrades.return_value = [mock_trade]

        orphan = {"order_id": 42, "order_ref": "SL_FALL_NVDA_200.0_20270115"}
        result = asyncio.run(_cancel_orphan_orders(mock_ib, [orphan]))

        assert result[0]["cancelled"] is True
        mock_ib.cancelOrder.assert_called_once_with(mock_trade.order)

    def test_reports_not_found_order(self):
        mock_ib = MagicMock()
        mock_ib.openTrades.return_value = []

        orphan = {"order_id": 99, "order_ref": "SL_FALL_NVDA_200.0_20270115"}
        result = asyncio.run(_cancel_orphan_orders(mock_ib, [orphan]))

        assert result[0]["cancelled"] is False
        assert "error" in result[0]

    def test_empty_orphan_list(self):
        mock_ib = MagicMock()
        mock_ib.openTrades.return_value = []
        result = asyncio.run(_cancel_orphan_orders(mock_ib, []))
        assert result == []


# ---------------------------------------------------------------------------
# _place_combo_stop_order
# ---------------------------------------------------------------------------


class TestPlaceComboStopOrder:
    def _make_qualified(self, con_id):
        qc = MagicMock()
        qc.conId = con_id
        return qc

    def test_places_order_successfully(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 101
        mock_ib.placeOrder.return_value = mock_trade

        pos = {
            "type": "pmcc",
            "symbol": "NVDA",
            "leaps": {"strike": 200.0, "expiry": "20270115", "right": "C", "avg_cost": 44.27},
            "shorts": [{"strike": 235.0, "expiry": "20260515", "right": "C", "qty": 3}],
        }
        qualified = [self._make_qualified(111), self._make_qualified(222)]

        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=qualified),
        ):
            result = asyncio.run(
                _place_combo_stop_order(mock_ib, pos, 3, 111, 22.0, "SL_FALL_NVDA_200.0_20270115")
            )

        assert result["ok"] is True
        assert result["order_id"] == 101

    def test_returns_error_when_qualify_fails(self):
        mock_ib = MagicMock()
        pos = {
            "type": "pmcc",
            "symbol": "NVDA",
            "leaps": {"strike": 200.0, "expiry": "20270115", "right": "C", "avg_cost": 44.27},
            "shorts": [{"strike": 235.0, "expiry": "20260515", "right": "C", "qty": 3}],
        }
        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=[]),  # qualification failed
        ):
            result = asyncio.run(
                _place_combo_stop_order(mock_ib, pos, 3, 111, 22.0, "SL_FALL_NVDA_200.0_20270115")
            )

        assert result["ok"] is False
        assert "error" in result

    def test_sets_order_account_from_position(self):
        """Regression for issue #39: combo order must be tagged with the
        position's account so IB routes execution to the holding account."""
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 101
        mock_ib.placeOrder.return_value = mock_trade

        pos = {
            "type": "pmcc",
            "symbol": "NVDA",
            "account": "U790497",
            "leaps": {"strike": 200.0, "expiry": "20270115", "right": "C", "avg_cost": 44.27},
            "shorts": [{"strike": 235.0, "expiry": "20260515", "right": "C", "qty": 3}],
        }
        qualified = [self._make_qualified(111), self._make_qualified(222)]
        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=qualified),
        ):
            asyncio.run(
                _place_combo_stop_order(mock_ib, pos, 3, 111, 22.0, "SL_FALL_NVDA_200.0_20270115")
            )

        placed_order = mock_ib.placeOrder.call_args[0][1]
        assert placed_order.account == "U790497"

    def test_does_not_set_order_account_when_position_lacks_it(self):
        """Backward-compat: omitting account leaves Order.account at default."""
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 101
        mock_ib.placeOrder.return_value = mock_trade

        pos = {
            "type": "pmcc",
            "symbol": "NVDA",
            "leaps": {"strike": 200.0, "expiry": "20270115", "right": "C", "avg_cost": 44.27},
            "shorts": [{"strike": 235.0, "expiry": "20260515", "right": "C", "qty": 3}],
        }
        qualified = [self._make_qualified(111), self._make_qualified(222)]
        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=qualified),
        ):
            asyncio.run(
                _place_combo_stop_order(mock_ib, pos, 3, 111, 22.0, "SL_FALL_NVDA_200.0_20270115")
            )

        placed_order = mock_ib.placeOrder.call_args[0][1]
        # ib_async Order default for account is empty string
        assert placed_order.account == ""


# ---------------------------------------------------------------------------
# _place_simple_stop_order
# ---------------------------------------------------------------------------


class TestPlaceSimpleStopOrder:
    def _make_qualified(self, con_id):
        qc = MagicMock()
        qc.conId = con_id
        return qc

    def test_places_leaps_order(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 202
        mock_ib.placeOrder.return_value = mock_trade

        pos = {
            "type": "leaps",
            "symbol": "NVDA",
            "leaps": {"strike": 200.0, "expiry": "20270115", "right": "C", "avg_cost": 44.27},
        }
        qualified = [self._make_qualified(333)]

        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=qualified),
        ):
            result = asyncio.run(
                _place_simple_stop_order(mock_ib, pos, 3, 333, 22.0, "SL_FALL_NVDA_200.0_20270115")
            )

        assert result["ok"] is True
        assert result["order_id"] == 202

    def test_places_stock_order(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 303
        mock_ib.placeOrder.return_value = mock_trade

        pos = {"type": "stock", "symbol": "AAPL", "avg_cost": 175.0}
        qualified = [self._make_qualified(444)]

        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=qualified),
        ):
            result = asyncio.run(
                _place_simple_stop_order(mock_ib, pos, 100, 444, 87.5, "SL_FALL_AAPL_STK")
            )

        assert result["ok"] is True
        assert result["order_id"] == 303

    def test_returns_error_when_qualify_fails(self):
        mock_ib = MagicMock()
        pos = {"type": "stock", "symbol": "AAPL", "avg_cost": 175.0}

        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=[]),
        ):
            result = asyncio.run(
                _place_simple_stop_order(mock_ib, pos, 100, 444, 87.5, "SL_FALL_AAPL_STK")
            )

        assert result["ok"] is False

    def test_sets_order_account_from_position_leaps(self):
        """Regression for issue #39: naked LEAPS order must carry position account."""
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 202
        mock_ib.placeOrder.return_value = mock_trade

        pos = {
            "type": "leaps",
            "symbol": "NVDA",
            "account": "U790497",
            "leaps": {"strike": 200.0, "expiry": "20270115", "right": "C", "avg_cost": 44.27},
        }
        qualified = [self._make_qualified(333)]
        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=qualified),
        ):
            asyncio.run(
                _place_simple_stop_order(mock_ib, pos, 3, 333, 22.0, "SL_FALL_NVDA_200.0_20270115")
            )

        placed_order = mock_ib.placeOrder.call_args[0][1]
        assert placed_order.account == "U790497"

    def test_sets_order_account_from_position_stock(self):
        """Regression for issue #39: stock order must carry position account."""
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 303
        mock_ib.placeOrder.return_value = mock_trade

        pos = {"type": "stock", "symbol": "AAPL", "account": "U790497", "avg_cost": 175.0}
        qualified = [self._make_qualified(444)]
        with patch(
            "trading_skills.broker.stop_loss.fetch_with_timeout",
            new=AsyncMock(return_value=qualified),
        ):
            asyncio.run(_place_simple_stop_order(mock_ib, pos, 100, 444, 87.5, "SL_FALL_AAPL_STK"))

        placed_order = mock_ib.placeOrder.call_args[0][1]
        assert placed_order.account == "U790497"


# ---------------------------------------------------------------------------
# _execute_position_stop
# ---------------------------------------------------------------------------


class TestExecutePositionStop:
    def _pmcc_analysis(self, action="place_new", stop_price=22.0):
        return {
            "type": "pmcc",
            "symbol": "NVDA",
            "qty": 3,
            "leaps": {"strike": 200.0, "expiry": "20270115", "right": "C"},
            "shorts": [{"strike": 235.0, "expiry": "20260515", "right": "C", "qty": 3}],
            "stop_loss": {"stop_price": stop_price, "action": action},
        }

    def test_skips_when_preserve_existing(self):
        mock_ib = MagicMock()
        result = asyncio.run(
            _execute_position_stop(mock_ib, self._pmcc_analysis("preserve_existing"), None, None)
        )
        assert result["skipped"] is True
        assert result["reason"] == "preserve_existing"

    def test_dispatches_pmcc_to_combo_order(self):
        mock_ib = MagicMock()
        expected = {"ok": True, "order_id": 1, "order_ref": "SL_FALL_NVDA_200.0_20270115"}

        with patch(
            "trading_skills.broker.stop_loss._place_combo_stop_order",
            new=AsyncMock(return_value=expected),
        ):
            result = asyncio.run(
                _execute_position_stop(
                    mock_ib, self._pmcc_analysis("place_new"), leaps_con_id=111, stock_con_id=None
                )
            )

        assert result["ok"] is True

    def test_dispatches_leaps_to_simple_order(self):
        mock_ib = MagicMock()
        analysis = {
            "type": "leaps",
            "symbol": "SOLO",
            "qty": 2,
            "leaps": {"strike": 50.0, "expiry": "20260918", "right": "C"},
            "stop_loss": {"stop_price": 5.0, "action": "place_new"},
        }
        expected = {"ok": True, "order_id": 2, "order_ref": "SL_FALL_SOLO_50.0_20260918"}

        with patch(
            "trading_skills.broker.stop_loss._place_simple_stop_order",
            new=AsyncMock(return_value=expected),
        ):
            result = asyncio.run(
                _execute_position_stop(mock_ib, analysis, leaps_con_id=222, stock_con_id=None)
            )

        assert result["ok"] is True

    def test_dispatches_stock_to_simple_order(self):
        mock_ib = MagicMock()
        analysis = {
            "type": "stock",
            "symbol": "AAPL",
            "qty": 100,
            "stop_loss": {"stop_price": 87.5, "action": "place_new"},
        }
        expected = {"ok": True, "order_id": 3, "order_ref": "SL_FALL_AAPL_STK"}

        with patch(
            "trading_skills.broker.stop_loss._place_simple_stop_order",
            new=AsyncMock(return_value=expected),
        ):
            result = asyncio.run(
                _execute_position_stop(mock_ib, analysis, leaps_con_id=None, stock_con_id=333)
            )

        assert result["ok"] is True

    def test_returns_error_when_pmcc_has_no_leaps_con_id(self):
        mock_ib = MagicMock()
        result = asyncio.run(
            _execute_position_stop(
                mock_ib, self._pmcc_analysis("place_new"), leaps_con_id=None, stock_con_id=None
            )
        )
        assert result["ok"] is False
        assert "error" in result

    def test_returns_error_when_stock_has_no_stock_con_id(self):
        mock_ib = MagicMock()
        analysis = {
            "type": "stock",
            "symbol": "AAPL",
            "qty": 100,
            "stop_loss": {"stop_price": 87.5, "action": "place_new"},
        }
        result = asyncio.run(
            _execute_position_stop(mock_ib, analysis, leaps_con_id=None, stock_con_id=None)
        )
        assert result["ok"] is False

    def test_skips_when_overwrite_action(self):
        mock_ib = MagicMock()
        expected = {"ok": True, "order_id": 10, "order_ref": "SL_FALL_NVDA_200.0_20270115"}

        with patch(
            "trading_skills.broker.stop_loss._place_combo_stop_order",
            new=AsyncMock(return_value=expected),
        ):
            result = asyncio.run(
                _execute_position_stop(
                    mock_ib, self._pmcc_analysis("overwrite"), leaps_con_id=111, stock_con_id=None
                )
            )

        assert result["ok"] is True

    def test_returns_error_when_leaps_has_no_leaps_con_id(self):
        mock_ib = MagicMock()
        analysis = {
            "type": "leaps",
            "symbol": "SOLO",
            "qty": 2,
            "leaps": {"strike": 50.0, "expiry": "20260918", "right": "C"},
            "stop_loss": {"stop_price": 5.0, "action": "place_new"},
        }
        result = asyncio.run(
            _execute_position_stop(mock_ib, analysis, leaps_con_id=None, stock_con_id=None)
        )
        assert result["ok"] is False

    def test_cancels_all_symbol_orders_before_placing_new(self):
        # Any existing conditional order for the symbol (manual or SL_) must be
        # cancelled before placing the new SL_ order, not just the exact-ref match.
        mock_ib = MagicMock()
        manual_trade = MagicMock()
        manual_trade.order.orderId = 77
        sl_trade = MagicMock()
        sl_trade.order.orderId = 78
        mock_ib.openTrades.return_value = [manual_trade, sl_trade]

        open_orders = [
            # Manual order for same symbol (empty order_ref)
            {
                "order_id": 77,
                "order_ref": "",
                "symbol": "NVDA",
                "conditions": [{"price": 1000.0, "is_more": True}],
            },
            # Stale SL_ order for same symbol with different key
            {
                "order_id": 78,
                "order_ref": "SL_FALL_NVDA_190.0_20270115",
                "symbol": "NVDA",
                "conditions": [{"price": 10.0, "is_more": False}],
            },
        ]

        expected = {"ok": True, "order_id": 99, "order_ref": "SL_FALL_NVDA_200.0_20270115"}
        with patch(
            "trading_skills.broker.stop_loss._place_combo_stop_order",
            new=AsyncMock(return_value=expected),
        ):
            asyncio.run(
                _execute_position_stop(
                    mock_ib,
                    self._pmcc_analysis("place_new"),
                    leaps_con_id=111,
                    stock_con_id=None,
                    open_orders=open_orders,
                )
            )

        # Both orders for the symbol must be cancelled
        cancelled_orders = [call.args[0] for call in mock_ib.cancelOrder.call_args_list]
        cancelled_ids = {o.orderId for o in cancelled_orders}
        assert cancelled_ids == {77, 78}


# ---------------------------------------------------------------------------
# get_stop_loss_data — minimal integration (mocked IB)
# ---------------------------------------------------------------------------

MODULE = "trading_skills.broker.stop_loss"


class TestGetStopLossData:
    def _make_mock_ib(self):
        mock_ib = MagicMock()
        mock_ib.managedAccounts.return_value = ["U123"]
        mock_ib.positions.return_value = []
        mock_ib.reqAllOpenOrdersAsync = AsyncMock(return_value=[])
        mock_ib.openTrades.return_value = []
        return mock_ib

    def _ib_context(self, mock_ib):
        @asynccontextmanager
        async def _ctx(*args, **kwargs):
            yield mock_ib

        return _ctx

    def test_returns_empty_positions_message(self):
        mock_ib = self._make_mock_ib()

        with (
            patch(f"{MODULE}.ib_connection", self._ib_context(mock_ib)),
            patch(f"{MODULE}.asyncio.sleep", new=AsyncMock()),
            patch(f"{MODULE}.fetch_with_timeout", new=AsyncMock(return_value=[])),
        ):
            result = asyncio.run(get_stop_loss_data(port=7497, dry_run=True))

        assert result["dry_run"] is True
        assert result["positions"] == []
        assert result["message"] == "No positions found"

    def test_returns_error_for_unknown_account(self):
        mock_ib = self._make_mock_ib()

        with (
            patch(f"{MODULE}.ib_connection", self._ib_context(mock_ib)),
            patch(f"{MODULE}.asyncio.sleep", new=AsyncMock()),
        ):
            result = asyncio.run(get_stop_loss_data(port=7497, account="UNKNOWN", dry_run=True))

        assert "error" in result

    def test_symbols_filter_applied(self):
        mock_ib = self._make_mock_ib()

        with (
            patch(f"{MODULE}.ib_connection", self._ib_context(mock_ib)),
            patch(f"{MODULE}.asyncio.sleep", new=AsyncMock()),
            patch(f"{MODULE}.fetch_with_timeout", new=AsyncMock(return_value=[])),
        ):
            result = asyncio.run(get_stop_loss_data(port=7497, symbols=["NVDA"], dry_run=True))

        assert result["symbols_filter"] == ["NVDA"]
        assert result["positions"] == []

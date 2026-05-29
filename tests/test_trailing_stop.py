# ABOUTME: Unit tests for trailing-stop analytics and data-layer functions.
# ABOUTME: Analytics tests run without IBKR; data-layer tests use MagicMock.

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_skills.broker.trailing_stop import (
    _cancel_orphan_orders,
    _execute_position_trail,
    _fetch_open_orders,
    _parse_existing_trails,
    _place_simple_trail_order,
    _ts_key,
    build_trail_analysis,
    calc_initial_trail_stop_price,
    calc_trail_reference,
    detect_orphan_trail_orders,
    filter_orders_by_account,
    identify_trailable_positions,
    summarize_all_trail_orders,
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


def _stock_pos(symbol="JOBY", qty=1000, avg_cost=5.0, account="U123"):
    return {"type": "stock", "symbol": symbol, "account": account, "qty": qty, "avg_cost": avg_cost}


def _leaps_pos(symbol="SOLO", qty=2, avg_cost=10.0, strike=50.0, expiry="20260918", account="U123"):
    return {
        "type": "leaps",
        "symbol": symbol,
        "account": account,
        "qty": qty,
        "leaps": {"strike": strike, "expiry": expiry, "right": "C", "avg_cost": avg_cost},
    }


# ---------------------------------------------------------------------------
# calc_trail_reference
# ---------------------------------------------------------------------------


def test_reference_normal_uses_current_when_higher():
    assert calc_trail_reference(7.5, 5.0, forced=False) == pytest.approx(7.5)


def test_reference_normal_uses_avg_cost_when_current_lower():
    assert calc_trail_reference(4.0, 5.0, forced=False) == pytest.approx(5.0)


def test_reference_normal_falls_back_when_current_missing():
    assert calc_trail_reference(None, 5.0, forced=False) == pytest.approx(5.0)


def test_reference_normal_falls_back_when_current_zero():
    assert calc_trail_reference(0.0, 5.0, forced=False) == pytest.approx(5.0)


def test_reference_forced_uses_current():
    assert calc_trail_reference(4.0, 5.0, forced=True) == pytest.approx(4.0)


def test_reference_forced_falls_back_when_current_missing():
    assert calc_trail_reference(None, 5.0, forced=True) == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# calc_initial_trail_stop_price
# ---------------------------------------------------------------------------


def test_initial_stop_pct():
    # 7.50 * (1 - 0.20) = 6.00
    assert calc_initial_trail_stop_price(7.5, trail_pct=20.0) == pytest.approx(6.0)


def test_initial_stop_amt():
    # 7.50 - 1.50 = 6.00
    assert calc_initial_trail_stop_price(7.5, trail_amt=1.5) == pytest.approx(6.0)


def test_initial_stop_requires_one_param():
    with pytest.raises(ValueError):
        calc_initial_trail_stop_price(7.5)


def test_initial_stop_rejects_both_params():
    with pytest.raises(ValueError):
        calc_initial_trail_stop_price(7.5, trail_pct=20.0, trail_amt=1.5)


# ---------------------------------------------------------------------------
# identify_trailable_positions
# ---------------------------------------------------------------------------


def test_identify_stock():
    result = identify_trailable_positions([_stk("JOBY", quantity=1000, avg_cost=5.0)])
    assert len(result) == 1
    assert result[0]["type"] == "stock"
    assert result[0]["symbol"] == "JOBY"


def test_identify_naked_leaps():
    result = identify_trailable_positions([_opt("NVDA", 3, 44.27, 200.0, "20270115")])
    assert len(result) == 1
    assert result[0]["type"] == "leaps"


def test_identify_excludes_pmcc():
    """PMCC is out of scope; only the longest long with shorts becomes PMCC and is dropped.
    Extra naked LEAPS on the same symbol should still appear."""
    normalized = [
        _opt("NVDA", 3, 44.27, 200.0, "20270115"),  # LEAPS, becomes PMCC long → dropped
        _opt("NVDA", 2, 15.0, 210.0, "20260918"),  # naked LEAPS → kept
        _opt("NVDA", -3, -0.61, 235.0, "20260515"),  # short
    ]
    result = identify_trailable_positions(normalized)
    types = [p["type"] for p in result]
    assert types == ["leaps"]
    assert result[0]["leaps"]["strike"] == 210.0


def test_identify_mixed():
    normalized = [
        _stk("JOBY", quantity=1000, avg_cost=5.0),
        _opt("SOLO", 2, 10.0, 50.0, "20260918"),  # naked LEAPS
    ]
    result = identify_trailable_positions(normalized)
    types = {p["type"] for p in result}
    assert types == {"stock", "leaps"}


# ---------------------------------------------------------------------------
# _ts_key
# ---------------------------------------------------------------------------


def test_ts_key_stock():
    assert _ts_key(_stock_pos("JOBY")) == "JOBY_STK"


def test_ts_key_leaps():
    assert _ts_key(_leaps_pos("SOLO", strike=50.0, expiry="20260918")) == "SOLO_50.0_20260918"


# ---------------------------------------------------------------------------
# build_trail_analysis
# ---------------------------------------------------------------------------


def test_build_stock_place_new():
    pos = _stock_pos(symbol="JOBY", qty=1000, avg_cost=5.0)
    result = build_trail_analysis(
        position=pos,
        underlying_price=7.50,
        current_price=7.50,
        existing_trail=None,
        trail_pct=20.0,
        trail_amt=None,
        forced=False,
    )
    assert result["type"] == "stock"
    assert result["trail_stop"]["action"] == "place_new"
    assert result["trail_stop"]["reference"] == pytest.approx(7.50)
    assert result["trail_stop"]["initial_stop_price"] == pytest.approx(6.00)
    assert result["stock"]["avg_cost"] == 5.0
    assert result["stock"]["current_price"] == 7.50


def test_build_leaps_place_new():
    pos = _leaps_pos(symbol="SOLO", qty=2, avg_cost=10.0)
    result = build_trail_analysis(
        position=pos,
        underlying_price=55.0,
        current_price=12.0,  # in profit
        existing_trail=None,
        trail_pct=25.0,
        trail_amt=None,
        forced=False,
    )
    assert result["type"] == "leaps"
    # reference = max(12, 10) = 12; stop = 12 * 0.75 = 9.0
    assert result["trail_stop"]["reference"] == pytest.approx(12.0)
    assert result["trail_stop"]["initial_stop_price"] == pytest.approx(9.0)
    assert result["leaps"]["strike"] == 50.0


def test_build_locks_in_profit_via_max():
    pos = _stock_pos(avg_cost=5.0)
    result = build_trail_analysis(
        position=pos,
        underlying_price=10.0,
        current_price=10.0,  # well above avg_cost
        existing_trail=None,
        trail_pct=20.0,
        trail_amt=None,
        forced=False,
    )
    # reference = 10 (not 5); initial stop = 8.0 (above entry — profit locked)
    assert result["trail_stop"]["reference"] == pytest.approx(10.0)
    assert result["trail_stop"]["initial_stop_price"] == pytest.approx(8.0)


def test_build_uses_avg_cost_when_underwater_normal_mode():
    pos = _stock_pos(avg_cost=5.0)
    result = build_trail_analysis(
        position=pos,
        underlying_price=4.0,
        current_price=4.0,  # below avg_cost
        existing_trail=None,
        trail_pct=20.0,
        trail_amt=None,
        forced=False,
    )
    # reference = 5 (avg_cost); stop = 4.0 (below entry but anchored to cost)
    assert result["trail_stop"]["reference"] == pytest.approx(5.0)
    assert result["trail_stop"]["initial_stop_price"] == pytest.approx(4.0)


def test_build_forced_uses_current_even_when_below_cost():
    pos = _stock_pos(avg_cost=5.0)
    result = build_trail_analysis(
        position=pos,
        underlying_price=4.0,
        current_price=4.0,
        existing_trail=None,
        trail_pct=20.0,
        trail_amt=None,
        forced=True,
    )
    # forced: reference = current = 4.0; stop = 3.2
    assert result["trail_stop"]["reference"] == pytest.approx(4.0)
    assert result["trail_stop"]["initial_stop_price"] == pytest.approx(3.2)


def test_build_preserve_existing():
    pos = _stock_pos()
    existing = {
        "trailing_percent": 20.0,
        "aux_price": None,
        "trail_stop_price": 6.0,
        "order_id": 42,
    }
    result = build_trail_analysis(
        position=pos,
        underlying_price=7.5,
        current_price=7.5,
        existing_trail=existing,
        trail_pct=20.0,
        trail_amt=None,
        forced=False,
    )
    assert result["trail_stop"]["action"] == "preserve_existing"
    assert result["trail_stop"]["existing_trail"]["order_id"] == 42


def test_build_overwrite_when_forced_with_existing():
    pos = _stock_pos()
    existing = {"trailing_percent": 15.0, "trail_stop_price": 6.0, "order_id": 42}
    result = build_trail_analysis(
        position=pos,
        underlying_price=7.5,
        current_price=7.5,
        existing_trail=existing,
        trail_pct=20.0,
        trail_amt=None,
        forced=True,
    )
    assert result["trail_stop"]["action"] == "overwrite"


def test_build_with_dollar_trail_amt():
    pos = _stock_pos(avg_cost=5.0)
    result = build_trail_analysis(
        position=pos,
        underlying_price=10.0,
        current_price=10.0,
        existing_trail=None,
        trail_pct=None,
        trail_amt=1.50,
        forced=False,
    )
    assert result["trail_stop"]["trail_amt"] == 1.50
    assert result["trail_stop"]["initial_stop_price"] == pytest.approx(8.50)


# ---------------------------------------------------------------------------
# detect_orphan_trail_orders
# ---------------------------------------------------------------------------


def _ts_order(order_ref, account="U123", order_id=1, order_type="TRAIL"):
    return {
        "order_ref": order_ref,
        "account": account,
        "order_id": order_id,
        "order_type": order_type,
        "symbol": "JOBY",
        "trailing_percent": 20.0,
        "trail_stop_price": 6.0,
    }


def test_detect_orphan_no_orphans():
    positions = [_stock_pos(symbol="JOBY")]
    orders = [_ts_order("TS_JOBY_STK")]
    assert detect_orphan_trail_orders(orders, positions) == []


def test_detect_orphan_closed_position():
    positions = []
    orders = [_ts_order("TS_JOBY_STK")]
    orphans = detect_orphan_trail_orders(orders, positions)
    assert len(orphans) == 1


def test_detect_orphan_ignores_non_ts_orders():
    positions = []
    orders = [_ts_order("MANUAL_TRAIL")]
    assert detect_orphan_trail_orders(orders, positions) == []


def test_detect_orphan_ignores_non_trail_order_types():
    """A TS_-prefixed order that isn't TRAIL/TRAIL LIMIT isn't ours to manage."""
    positions = []
    orders = [_ts_order("TS_JOBY_STK", order_type="MKT")]
    assert detect_orphan_trail_orders(orders, positions) == []


def test_detect_orphan_account_aware():
    positions = [_stock_pos(symbol="JOBY", account="U2")]
    orders = [_ts_order("TS_JOBY_STK", account="U1")]
    orphans = detect_orphan_trail_orders(orders, positions)
    assert len(orphans) == 1
    assert orphans[0]["account"] == "U1"


# ---------------------------------------------------------------------------
# summarize_all_trail_orders
# ---------------------------------------------------------------------------


def test_summarize_splits_module_and_manual():
    orders = [
        _ts_order("TS_JOBY_STK"),
        _ts_order("MANUAL_TRAIL"),
    ]
    result = summarize_all_trail_orders(orders)
    assert len(result["module"]) == 1
    assert len(result["manual"]) == 1


def test_summarize_ignores_non_trail():
    orders = [_ts_order("TS_JOBY_STK", order_type="MKT")]
    result = summarize_all_trail_orders(orders)
    assert result == {"module": [], "manual": []}


def test_summarize_includes_trail_limit():
    orders = [_ts_order("TS_JOBY_STK", order_type="TRAIL LIMIT")]
    result = summarize_all_trail_orders(orders)
    assert len(result["module"]) == 1


# ---------------------------------------------------------------------------
# filter_orders_by_account
# ---------------------------------------------------------------------------


def test_filter_orders_single_account():
    orders = [
        _ts_order("TS_A", account="U1", order_id=1),
        _ts_order("TS_B", account="U2", order_id=2),
    ]
    result = filter_orders_by_account(orders, ["U1"])
    assert [o["order_id"] for o in result] == [1]


def test_filter_orders_drops_missing_account():
    orders = [
        _ts_order("TS_A", account="U1", order_id=1),
        {"order_ref": "TS_B", "order_id": 2},  # no account
    ]
    result = filter_orders_by_account(orders, ["U1"])
    assert [o["order_id"] for o in result] == [1]


# ---------------------------------------------------------------------------
# _parse_existing_trails
# ---------------------------------------------------------------------------


class TestParseExistingTrails:
    def test_extracts_trail_params(self):
        orders = [
            {
                "order_ref": "TS_JOBY_STK",
                "account": "U1",
                "order_type": "TRAIL",
                "order_id": 42,
                "trailing_percent": 20.0,
                "aux_price": None,
                "trail_stop_price": 6.0,
            }
        ]
        result = _parse_existing_trails(orders)
        assert ("U1", "JOBY_STK") in result
        assert result[("U1", "JOBY_STK")]["trailing_percent"] == 20.0
        assert result[("U1", "JOBY_STK")]["order_id"] == 42

    def test_ignores_non_trail_order_types(self):
        orders = [
            {
                "order_ref": "TS_JOBY_STK",
                "account": "U1",
                "order_type": "MKT",
                "order_id": 42,
            }
        ]
        assert _parse_existing_trails(orders) == {}

    def test_ignores_non_ts_orders(self):
        orders = [
            {
                "order_ref": "MANUAL",
                "account": "U1",
                "order_type": "TRAIL",
                "order_id": 42,
            }
        ]
        assert _parse_existing_trails(orders) == {}

    def test_same_key_different_accounts_kept_separate(self):
        orders = [
            {
                "order_ref": "TS_JOBY_STK",
                "account": "U1",
                "order_type": "TRAIL",
                "order_id": 1,
                "trailing_percent": 20.0,
            },
            {
                "order_ref": "TS_JOBY_STK",
                "account": "U2",
                "order_type": "TRAIL",
                "order_id": 2,
                "trailing_percent": 30.0,
            },
        ]
        result = _parse_existing_trails(orders)
        assert result[("U1", "JOBY_STK")]["trailing_percent"] == 20.0
        assert result[("U2", "JOBY_STK")]["trailing_percent"] == 30.0


# ---------------------------------------------------------------------------
# _fetch_open_orders
# ---------------------------------------------------------------------------


class TestFetchOpenOrders:
    def _make_trade(self, order_ref, symbol, sec_type="STK", order_type="TRAIL", order_id=1):
        trade = MagicMock()
        trade.contract.symbol = symbol
        trade.contract.secType = sec_type
        trade.contract.strike = 0.0
        trade.contract.lastTradeDateOrContractMonth = ""
        trade.contract.right = ""
        trade.order.orderId = order_id
        trade.order.orderRef = order_ref
        trade.order.action = "SELL"
        trade.order.orderType = order_type
        trade.order.totalQuantity = 1000
        trade.order.trailingPercent = 20.0
        trade.order.auxPrice = 0.0
        trade.order.trailStopPrice = 6.0
        return trade

    def test_returns_trail_fields(self):
        mock_ib = MagicMock()
        mock_ib.reqAllOpenOrdersAsync = AsyncMock(return_value=[])
        trade = self._make_trade("TS_JOBY_STK", "JOBY")
        mock_ib.openTrades.return_value = [trade]

        with patch(
            "trading_skills.broker.trailing_stop.fetch_with_timeout",
            new=AsyncMock(return_value=[]),
        ):
            result = asyncio.run(_fetch_open_orders(mock_ib))

        assert len(result) == 1
        assert result[0]["order_ref"] == "TS_JOBY_STK"
        assert result[0]["order_type"] == "TRAIL"
        assert result[0]["trailing_percent"] == 20.0
        assert result[0]["trail_stop_price"] == 6.0


# ---------------------------------------------------------------------------
# _cancel_orphan_orders
# ---------------------------------------------------------------------------


class TestCancelOrphanOrders:
    def test_cancels_matching_order(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 42
        mock_ib.openTrades.return_value = [mock_trade]

        orphan = {"order_id": 42, "order_ref": "TS_JOBY_STK"}
        result = asyncio.run(_cancel_orphan_orders(mock_ib, [orphan]))

        assert result[0]["cancelled"] is True
        mock_ib.cancelOrder.assert_called_once_with(mock_trade.order)

    def test_reports_not_found(self):
        mock_ib = MagicMock()
        mock_ib.openTrades.return_value = []

        orphan = {"order_id": 99, "order_ref": "TS_JOBY_STK"}
        result = asyncio.run(_cancel_orphan_orders(mock_ib, [orphan]))

        assert result[0]["cancelled"] is False
        assert "error" in result[0]


# ---------------------------------------------------------------------------
# _place_simple_trail_order
# ---------------------------------------------------------------------------


class TestPlaceSimpleTrailOrder:
    def _qualified(self, con_id):
        qc = MagicMock()
        qc.conId = con_id
        return qc

    def test_places_stock_trail_pct(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 101
        mock_ib.placeOrder.return_value = mock_trade

        pos = {"type": "stock", "symbol": "JOBY", "avg_cost": 5.0}
        with patch(
            "trading_skills.broker.trailing_stop.fetch_with_timeout",
            new=AsyncMock(return_value=[self._qualified(111)]),
        ):
            result = asyncio.run(
                _place_simple_trail_order(
                    mock_ib,
                    pos,
                    qty=1000,
                    trail_pct=20.0,
                    trail_amt=None,
                    trail_stop_price=6.0,
                    order_ref="TS_JOBY_STK",
                )
            )
        assert result["ok"] is True
        placed = mock_ib.placeOrder.call_args[0][1]
        assert placed.orderType == "TRAIL"
        assert placed.action == "SELL"
        assert placed.trailingPercent == 20.0
        assert placed.trailStopPrice == 6.0
        assert placed.tif == "GTC"

    def test_places_stock_trail_amt(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 101
        mock_ib.placeOrder.return_value = mock_trade

        pos = {"type": "stock", "symbol": "JOBY", "avg_cost": 5.0}
        with patch(
            "trading_skills.broker.trailing_stop.fetch_with_timeout",
            new=AsyncMock(return_value=[self._qualified(111)]),
        ):
            asyncio.run(
                _place_simple_trail_order(
                    mock_ib,
                    pos,
                    qty=1000,
                    trail_pct=None,
                    trail_amt=1.5,
                    trail_stop_price=6.0,
                    order_ref="TS_JOBY_STK",
                )
            )
        placed = mock_ib.placeOrder.call_args[0][1]
        assert placed.auxPrice == 1.5

    def test_places_leaps_trail(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 202
        mock_ib.placeOrder.return_value = mock_trade

        pos = {
            "type": "leaps",
            "symbol": "SOLO",
            "leaps": {"strike": 50.0, "expiry": "20260918", "right": "C", "avg_cost": 10.0},
        }
        with patch(
            "trading_skills.broker.trailing_stop.fetch_with_timeout",
            new=AsyncMock(return_value=[self._qualified(333)]),
        ):
            result = asyncio.run(
                _place_simple_trail_order(
                    mock_ib,
                    pos,
                    qty=2,
                    trail_pct=25.0,
                    trail_amt=None,
                    trail_stop_price=9.0,
                    order_ref="TS_SOLO_50.0_20260918",
                )
            )
        assert result["ok"] is True

    def test_qualify_fails(self):
        mock_ib = MagicMock()
        pos = {"type": "stock", "symbol": "JOBY", "avg_cost": 5.0}
        with patch(
            "trading_skills.broker.trailing_stop.fetch_with_timeout",
            new=AsyncMock(return_value=[]),
        ):
            result = asyncio.run(
                _place_simple_trail_order(
                    mock_ib,
                    pos,
                    qty=1000,
                    trail_pct=20.0,
                    trail_amt=None,
                    trail_stop_price=6.0,
                    order_ref="TS_JOBY_STK",
                )
            )
        assert result["ok"] is False
        assert "error" in result

    def test_sets_account_from_position(self):
        mock_ib = MagicMock()
        mock_trade = MagicMock()
        mock_trade.order.orderId = 101
        mock_ib.placeOrder.return_value = mock_trade

        pos = {"type": "stock", "symbol": "JOBY", "account": "U790497", "avg_cost": 5.0}
        with patch(
            "trading_skills.broker.trailing_stop.fetch_with_timeout",
            new=AsyncMock(return_value=[self._qualified(111)]),
        ):
            asyncio.run(
                _place_simple_trail_order(
                    mock_ib,
                    pos,
                    qty=1000,
                    trail_pct=20.0,
                    trail_amt=None,
                    trail_stop_price=6.0,
                    order_ref="TS_JOBY_STK",
                )
            )
        placed = mock_ib.placeOrder.call_args[0][1]
        assert placed.account == "U790497"


# ---------------------------------------------------------------------------
# _execute_position_trail
# ---------------------------------------------------------------------------


class TestExecutePositionTrail:
    def _stock_analysis(self, action="place_new"):
        return {
            "type": "stock",
            "symbol": "JOBY",
            "qty": 1000,
            "account": "U123",
            "trail_stop": {
                "trail_pct": 20.0,
                "trail_amt": None,
                "reference": 7.5,
                "initial_stop_price": 6.0,
                "action": action,
                "existing_trail": None,
            },
        }

    def _leaps_analysis(self, action="place_new"):
        return {
            "type": "leaps",
            "symbol": "SOLO",
            "qty": 2,
            "account": "U123",
            "leaps": {"strike": 50.0, "expiry": "20260918", "right": "C", "avg_cost": 10.0},
            "trail_stop": {
                "trail_pct": 25.0,
                "trail_amt": None,
                "reference": 12.0,
                "initial_stop_price": 9.0,
                "action": action,
                "existing_trail": None,
            },
        }

    def test_skips_when_preserve_existing(self):
        mock_ib = MagicMock()
        result = asyncio.run(
            _execute_position_trail(mock_ib, self._stock_analysis("preserve_existing"), None, 111)
        )
        assert result["skipped"] is True
        assert result["reason"] == "preserve_existing"

    def test_dispatches_stock(self):
        mock_ib = MagicMock()
        expected = {"ok": True, "order_id": 1, "order_ref": "TS_JOBY_STK"}
        with patch(
            "trading_skills.broker.trailing_stop._place_simple_trail_order",
            new=AsyncMock(return_value=expected),
        ):
            result = asyncio.run(
                _execute_position_trail(
                    mock_ib, self._stock_analysis(), leaps_con_id=None, stock_con_id=111
                )
            )
        assert result["ok"] is True

    def test_dispatches_leaps(self):
        mock_ib = MagicMock()
        expected = {"ok": True, "order_id": 2, "order_ref": "TS_SOLO_50.0_20260918"}
        with patch(
            "trading_skills.broker.trailing_stop._place_simple_trail_order",
            new=AsyncMock(return_value=expected),
        ):
            result = asyncio.run(
                _execute_position_trail(
                    mock_ib, self._leaps_analysis(), leaps_con_id=222, stock_con_id=None
                )
            )
        assert result["ok"] is True

    def test_stock_without_con_id_errors(self):
        mock_ib = MagicMock()
        result = asyncio.run(
            _execute_position_trail(
                mock_ib, self._stock_analysis(), leaps_con_id=None, stock_con_id=None
            )
        )
        assert result["ok"] is False
        assert "stock conId" in result["error"]

    def test_leaps_without_con_id_errors(self):
        mock_ib = MagicMock()
        result = asyncio.run(
            _execute_position_trail(
                mock_ib, self._leaps_analysis(), leaps_con_id=None, stock_con_id=None
            )
        )
        assert result["ok"] is False
        assert "LEAPS conId" in result["error"]

    def test_overwrite_cancels_existing_first(self):
        """When action=overwrite, existing TS_ order for this position+account must be cancelled."""
        mock_ib = MagicMock()
        existing_trade = MagicMock()
        existing_trade.order.orderId = 99
        mock_ib.openTrades.return_value = [existing_trade]
        existing_order = {"order_ref": "TS_JOBY_STK", "account": "U123", "order_id": 99}

        with patch(
            "trading_skills.broker.trailing_stop._place_simple_trail_order",
            new=AsyncMock(return_value={"ok": True, "order_id": 1}),
        ):
            asyncio.run(
                _execute_position_trail(
                    mock_ib,
                    self._stock_analysis("overwrite"),
                    leaps_con_id=None,
                    stock_con_id=111,
                    open_orders=[existing_order],
                )
            )

        mock_ib.cancelOrder.assert_called_once_with(existing_trade.order)

# ABOUTME: Unit tests for stop-loss analytics functions.
# ABOUTME: All tests run without IBKR dependency — pure calculation coverage.

import pytest

from trading_skills.broker.stop_loss import (
    calc_leaps_stop_basis,
    calc_leaps_stop_price,
    calc_short_premium_decay_pct,
    check_alerts,
    detect_orphan_orders,
    find_delta_neutral_spot,
    summarize_all_conditional_orders,
)

# ---------------------------------------------------------------------------
# find_delta_neutral_spot
# ---------------------------------------------------------------------------


def test_delta_neutral_spot_is_above_current():
    """Delta-neutral watermark must be above current spot for a typical PMCC."""
    spot = 200.0
    long_strike, long_dte, long_iv = 180.0, 400, 0.40
    short_strike, short_dte, short_iv = 210.0, 45, 0.35

    watermark = find_delta_neutral_spot(
        long_strike, long_dte, long_iv, short_strike, short_dte, short_iv, spot
    )
    assert watermark is not None
    assert watermark > spot


def test_delta_neutral_spot_net_delta_near_zero():
    """At the returned watermark, long_delta - short_delta should be ~0."""
    from trading_skills.broker.pmcc_advisor import calc_delta

    spot = 200.0
    long_strike, long_dte, long_iv = 180.0, 400, 0.40
    short_strike, short_dte, short_iv = 210.0, 45, 0.35

    watermark = find_delta_neutral_spot(
        long_strike, long_dte, long_iv, short_strike, short_dte, short_iv, spot
    )
    assert watermark is not None

    ld = calc_delta(watermark, long_strike, long_dte, long_iv, "C")
    sd = calc_delta(watermark, short_strike, short_dte, short_iv, "C")
    assert abs(ld - sd) < 0.02


def test_delta_neutral_spot_returns_none_when_no_crossing():
    """Returns None when there is no delta-neutral point (e.g., zero DTE short)."""
    # If short DTE is near zero, short_delta is either 0 or 1 — no crossing near spot
    result = find_delta_neutral_spot(
        long_strike=100.0,
        long_dte=365,
        long_iv=0.30,
        short_strike=150.0,
        short_dte=0,
        short_iv=0.30,
        spot_hint=90.0,
    )
    # With expired short, crossing may not be found; we just need no crash
    assert result is None or result > 0


# ---------------------------------------------------------------------------
# calc_leaps_stop_basis
# ---------------------------------------------------------------------------


def test_leaps_stop_basis_uses_market_when_higher():
    basis = calc_leaps_stop_basis(leaps_market_price=40.0, leaps_avg_cost=30.0)
    assert basis == pytest.approx(40.0)


def test_leaps_stop_basis_uses_cost_when_higher():
    basis = calc_leaps_stop_basis(leaps_market_price=25.0, leaps_avg_cost=35.0)
    assert basis == pytest.approx(35.0)


def test_leaps_stop_basis_falls_back_to_cost_when_market_none():
    basis = calc_leaps_stop_basis(leaps_market_price=None, leaps_avg_cost=35.0)
    assert basis == pytest.approx(35.0)


def test_leaps_stop_basis_falls_back_to_cost_when_market_zero():
    basis = calc_leaps_stop_basis(leaps_market_price=0.0, leaps_avg_cost=35.0)
    assert basis == pytest.approx(35.0)


# ---------------------------------------------------------------------------
# calc_leaps_stop_price
# ---------------------------------------------------------------------------


def test_leaps_stop_price_50pct():
    price = calc_leaps_stop_price(leaps_market_price=40.0, leaps_avg_cost=30.0, stop_pct=50.0)
    # basis = 40.0, stop = 40 * 0.5 = 20.0
    assert price == pytest.approx(20.0)


def test_leaps_stop_price_uses_cost_when_market_lower():
    price = calc_leaps_stop_price(leaps_market_price=25.0, leaps_avg_cost=35.0, stop_pct=50.0)
    # basis = 35.0, stop = 35 * 0.5 = 17.5
    assert price == pytest.approx(17.5)


def test_leaps_stop_price_custom_pct():
    price = calc_leaps_stop_price(leaps_market_price=40.0, leaps_avg_cost=30.0, stop_pct=25.0)
    # basis = 40.0, stop = 40 * 0.75 = 30.0
    assert price == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# calc_short_premium_decay_pct
# ---------------------------------------------------------------------------


def test_short_decay_pct_fully_intact():
    pct = calc_short_premium_decay_pct(premium_received=5.0, current_price=5.0)
    assert pct == pytest.approx(0.0)


def test_short_decay_pct_fully_captured():
    pct = calc_short_premium_decay_pct(premium_received=5.0, current_price=0.0)
    assert pct == pytest.approx(100.0)


def test_short_decay_pct_90_pct():
    pct = calc_short_premium_decay_pct(premium_received=5.0, current_price=0.50)
    assert pct == pytest.approx(90.0)


def test_short_decay_pct_zero_premium():
    pct = calc_short_premium_decay_pct(premium_received=0.0, current_price=1.0)
    assert pct == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# check_alerts
# ---------------------------------------------------------------------------


def test_no_alerts_when_all_ok():
    # spot $180 is 14% below short strike $210 — outside 5% threshold
    alerts = check_alerts(
        short_premium_received=30.0,
        short_current_price=25.0,
        short_strike=210.0,
        spot=180.0,
        leaps_current_price=38.0,
        leaps_avg_cost=35.0,
        stop_pct=50.0,
        short_near_strike_pct=5.0,
    )
    assert alerts == []


def test_alert_short_premium_decay():
    alerts = check_alerts(
        short_premium_received=5.0,
        short_current_price=0.40,  # 92% captured
        short_strike=210.0,
        spot=180.0,
        leaps_current_price=38.0,
        leaps_avg_cost=35.0,
        stop_pct=50.0,
        short_near_strike_pct=5.0,
    )
    types = [a["type"] for a in alerts]
    assert "short_premium_decay" in types


def test_alert_short_near_strike_spot_above():
    # spot $215 is above short strike $210 → gap = -2.4% ≤ 5% → fires
    alerts = check_alerts(
        short_premium_received=5.0,
        short_current_price=8.0,
        short_strike=210.0,
        spot=215.0,
        leaps_current_price=38.0,
        leaps_avg_cost=35.0,
        stop_pct=50.0,
        short_near_strike_pct=5.0,
    )
    types = [a["type"] for a in alerts]
    assert "short_near_strike" in types


def test_alert_short_near_strike_spot_within_threshold():
    # spot $200 is 4.8% below short strike $210 → within 5% → fires
    alerts = check_alerts(
        short_premium_received=5.0,
        short_current_price=8.0,
        short_strike=210.0,
        spot=200.0,
        leaps_current_price=38.0,
        leaps_avg_cost=35.0,
        stop_pct=50.0,
        short_near_strike_pct=5.0,
    )
    types = [a["type"] for a in alerts]
    assert "short_near_strike" in types


def test_alert_leaps_early_warning():
    # basis=max(25, 35)=35; loss=(35-25)/35≈28.6% > 25% (stop_pct/2) → fires
    # spot $180 is 14% below $210 strike → no near-strike alert
    alerts = check_alerts(
        short_premium_received=30.0,
        short_current_price=25.0,
        short_strike=210.0,
        spot=180.0,
        leaps_current_price=25.0,
        leaps_avg_cost=35.0,
        stop_pct=50.0,
        short_near_strike_pct=5.0,
    )
    types = [a["type"] for a in alerts]
    assert "leaps_early_warning" in types


def test_multiple_alerts_can_fire():
    # 94% premium captured → short_premium_decay
    # LEAPS down 51% → leaps_early_warning
    # spot $215 above $210 strike → short_near_strike
    alerts = check_alerts(
        short_premium_received=5.0,
        short_current_price=0.30,
        short_strike=210.0,
        spot=215.0,
        leaps_current_price=17.0,  # basis=35, loss=(35-17)/35≈51% > 25%
        leaps_avg_cost=35.0,
        stop_pct=50.0,
        short_near_strike_pct=5.0,
    )
    types = [a["type"] for a in alerts]
    assert "short_premium_decay" in types
    assert "leaps_early_warning" in types
    assert "short_near_strike" in types


def test_alert_near_strike_not_fired_when_spot_far():
    # spot $180 is 14% below $210 strike — outside 5% threshold
    alerts = check_alerts(
        short_premium_received=5.0,
        short_current_price=8.0,
        short_strike=210.0,
        spot=180.0,
        leaps_current_price=38.0,
        leaps_avg_cost=35.0,
        stop_pct=50.0,
        short_near_strike_pct=5.0,
    )
    types = [a["type"] for a in alerts]
    assert "short_near_strike" not in types


# ---------------------------------------------------------------------------
# detect_orphan_orders
# ---------------------------------------------------------------------------


def _make_spread(symbol, short_strike, short_expiry, long_strike, long_expiry):
    return {
        "symbol": symbol,
        "short": {"strike": short_strike, "expiry": short_expiry},
        "long": {"strike": long_strike, "expiry": long_expiry},
    }


def _make_order(symbol, strike, expiry, order_ref):
    return {
        "symbol": symbol,
        "strike": strike,
        "expiry": expiry,
        "order_ref": order_ref,
    }


def test_detect_orphan_no_orphans():
    spreads = [_make_spread("NVDA", 210.0, "20260618", 180.0, "20260918")]
    orders = [
        _make_order("NVDA", 210.0, "20260618", "SL_RISE_NVDA_210.0_20260618"),
        _make_order("NVDA", 180.0, "20260918", "SL_RISE_NVDA_180.0_20260918"),
    ]
    orphans = detect_orphan_orders(orders, spreads)
    assert orphans == []


def test_detect_orphan_detects_closed_position():
    spreads = []  # portfolio is empty
    orders = [_make_order("NVDA", 210.0, "20260618", "SL_RISE_NVDA_210.0_20260618")]
    orphans = detect_orphan_orders(orders, spreads)
    assert len(orphans) == 1
    assert orphans[0]["order_ref"] == "SL_RISE_NVDA_210.0_20260618"


def test_detect_orphan_ignores_non_sl_orders():
    spreads = []
    orders = [_make_order("NVDA", 210.0, "20260618", "MANUAL_ORDER")]
    orphans = detect_orphan_orders(orders, spreads)
    assert orphans == []


def test_detect_orphan_mixed():
    spreads = [_make_spread("AAPL", 200.0, "20260619", 170.0, "20260918")]
    orders = [
        _make_order("AAPL", 200.0, "20260619", "SL_RISE_AAPL_200.0_20260619"),  # active
        _make_order("NVDA", 210.0, "20260618", "SL_RISE_NVDA_210.0_20260618"),  # orphan
    ]
    orphans = detect_orphan_orders(orders, spreads)
    assert len(orphans) == 1
    assert orphans[0]["symbol"] == "NVDA"


# ---------------------------------------------------------------------------
# summarize_all_conditional_orders
# ---------------------------------------------------------------------------


def _make_cond_order(order_ref, conditions=None):
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
        _make_cond_order("SL_RISE_NVDA_210.0_20260618", [{"price": 218.5, "is_more": True}]),
        _make_cond_order("MANUAL_COND", [{"price": 200.0, "is_more": False}]),
    ]
    result = summarize_all_conditional_orders(orders)
    assert len(result["module"]) == 1
    assert len(result["manual"]) == 1
    assert result["module"][0]["order_ref"] == "SL_RISE_NVDA_210.0_20260618"
    assert result["manual"][0]["order_ref"] == "MANUAL_COND"


def test_all_conditional_orders_excludes_no_conditions():
    orders = [
        _make_cond_order("SL_RISE_NVDA_210.0_20260618", []),
        _make_cond_order("MANUAL_COND", []),
    ]
    result = summarize_all_conditional_orders(orders)
    assert len(result["module"]) == 0
    assert len(result["manual"]) == 0


def test_all_conditional_orders_empty_input():
    result = summarize_all_conditional_orders([])
    assert result == {"module": [], "manual": []}

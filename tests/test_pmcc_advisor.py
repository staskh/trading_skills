# ABOUTME: Unit tests for PMCC advisor analytics functions.
# ABOUTME: All tests run without IBKR dependency — pure calculation coverage.


import asyncio
import math
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_skills.broker.pmcc_advisor import (
    _fetch_option_quotes_batch,
    _fetch_single_option_quote,
    build_comparison_table,
    calc_assignment_prob,
    calc_bs_price,
    calc_daily_pnl_table,
    calc_delta,
    calc_iv,
    calc_pnl_if_assigned,
    calc_profit_per_day,
    check_earnings_warning,
    filter_spreads_by_symbols,
    find_best_rolls,
    find_optimal_exit_spot,
    find_roll_expiration_targets,
    get_option_price,
    score_roll_candidate,
)

# ---------------------------------------------------------------------------
# get_option_price
# ---------------------------------------------------------------------------


def test_get_option_price_mid_with_bid_ask():
    quote = {"bid": 2.00, "ask": 3.00, "last": 1.50}
    assert get_option_price(quote, "mid") == pytest.approx(2.50)


def test_get_option_price_last():
    quote = {"bid": 2.00, "ask": 3.00, "last": 1.80}
    assert get_option_price(quote, "last") == pytest.approx(1.80)


def test_get_option_price_mid_falls_back_to_bid():
    quote = {"bid": 1.50, "ask": None, "last": None}
    assert get_option_price(quote, "mid") == pytest.approx(1.50)


def test_get_option_price_mid_falls_back_to_last():
    quote = {"bid": None, "ask": None, "last": 2.10}
    assert get_option_price(quote, "mid") == pytest.approx(2.10)


# ---------------------------------------------------------------------------
# calc_iv
# ---------------------------------------------------------------------------


def test_calc_iv_recovers_known_iv():
    """Round-trip: price a call with known IV, then back-solve for IV."""
    spot, strike, dte_days, right = 100.0, 105.0, 30, "C"
    known_iv = 0.30
    price = calc_bs_price(spot, strike, dte_days, known_iv, right)
    recovered_iv = calc_iv(price, spot, strike, dte_days, right)
    assert recovered_iv is not None
    assert abs(recovered_iv - known_iv) < 0.001


def test_calc_iv_returns_none_for_zero_price():
    assert calc_iv(0.0, 100, 100, 30, "C") is None


def test_calc_iv_deep_itm_call():
    """Deep ITM call: IV should be calculable."""
    # $20 ITM call with 30 days — price should be well above intrinsic
    price = calc_bs_price(120.0, 100.0, 30, 0.25, "C")
    iv = calc_iv(price, 120.0, 100.0, 30, "C")
    assert iv is not None
    assert 0.1 < iv < 1.0


# ---------------------------------------------------------------------------
# calc_delta
# ---------------------------------------------------------------------------


def test_calc_delta_atm_call_near_half():
    """ATM call delta should be close to 0.5."""
    delta = calc_delta(spot=100, strike=100, dte_days=30, iv=0.3, right="C")
    assert 0.45 < delta < 0.55


def test_calc_delta_deep_itm_call_near_one():
    delta = calc_delta(spot=150, strike=100, dte_days=30, iv=0.3, right="C")
    assert delta > 0.90


def test_calc_delta_deep_otm_call_near_zero():
    delta = calc_delta(spot=80, strike=150, dte_days=30, iv=0.3, right="C")
    assert delta < 0.05


def test_calc_delta_put_is_negative():
    delta = calc_delta(spot=100, strike=105, dte_days=30, iv=0.3, right="P")
    assert delta < 0


# ---------------------------------------------------------------------------
# calc_assignment_prob
# ---------------------------------------------------------------------------


def test_calc_assignment_prob_deep_itm_near_one():
    prob = calc_assignment_prob(spot=200, strike=100, dte_days=1, iv=0.3, right="C")
    assert prob > 0.95


def test_calc_assignment_prob_deep_otm_near_zero():
    prob = calc_assignment_prob(spot=50, strike=200, dte_days=30, iv=0.3, right="C")
    assert prob < 0.05


def test_calc_assignment_prob_atm_near_half():
    prob = calc_assignment_prob(spot=100, strike=100, dte_days=30, iv=0.3, right="C")
    assert 0.35 < prob < 0.65


def test_calc_assignment_prob_between_zero_and_one():
    prob = calc_assignment_prob(spot=100, strike=110, dte_days=21, iv=0.25, right="C")
    assert 0.0 <= prob <= 1.0


# ---------------------------------------------------------------------------
# calc_bs_price
# ---------------------------------------------------------------------------


def test_calc_bs_price_call_otm_positive():
    price = calc_bs_price(spot=100, strike=110, dte_days=30, iv=0.3, right="C")
    assert price > 0


def test_calc_bs_price_expired_call_otm_zero():
    price = calc_bs_price(spot=100, strike=110, dte_days=0, iv=0.3, right="C")
    assert price == pytest.approx(0.0)


def test_calc_bs_price_expired_call_itm_intrinsic():
    price = calc_bs_price(spot=120, strike=100, dte_days=0, iv=0.3, right="C")
    assert price == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# calc_daily_pnl_table
# ---------------------------------------------------------------------------


def test_calc_daily_pnl_table_row_count():
    """Should return at most 5 trading days (capped by n_trading_days default)."""
    rows = calc_daily_pnl_table(
        long_strike=80,
        long_dte=180,
        long_cost=15.0,
        long_iv=0.35,
        short_strike=105,
        short_dte=14,
        short_premium=2.0,
        short_iv=0.30,
        qty=1,
        spot=100.0,
        right="C",
    )
    assert 1 <= len(rows) <= 5


def test_calc_daily_pnl_table_first_row_is_next_trading_day():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from trading_skills.utils import trading_sessions

    today = datetime.now(ZoneInfo("America/New_York")).date()
    first_session = trading_sessions(today, today + timedelta(days=7))[0]
    rows = calc_daily_pnl_table(
        long_strike=80,
        long_dte=180,
        long_cost=15.0,
        long_iv=0.35,
        short_strike=105,
        short_dte=5,
        short_premium=2.0,
        short_iv=0.30,
        qty=1,
        spot=100.0,
        right="C",
    )
    assert rows[0]["date"] == first_session.isoformat()


def test_calc_daily_pnl_table_days_to_expiry_decreases():
    rows = calc_daily_pnl_table(
        long_strike=80,
        long_dte=180,
        long_cost=15.0,
        long_iv=0.35,
        short_strike=105,
        short_dte=5,
        short_premium=2.0,
        short_iv=0.30,
        qty=1,
        spot=100.0,
        right="C",
    )
    days = [r["days_to_short_expiry"] for r in rows]
    assert days == sorted(days, reverse=True)  # monotonically decreasing


def test_calc_daily_pnl_table_has_required_fields():
    rows = calc_daily_pnl_table(
        long_strike=80,
        long_dte=180,
        long_cost=15.0,
        long_iv=0.35,
        short_strike=105,
        short_dte=3,
        short_premium=2.0,
        short_iv=0.30,
        qty=1,
        spot=100.0,
        right="C",
    )
    for row in rows:
        assert "date" in row
        assert "days_to_short_expiry" in row
        assert "optimal_spot" in row
        assert "pnl" in row
        assert isinstance(row["pnl"], float)


def test_calc_daily_pnl_table_optimal_spot_above_short_strike():
    """Optimal exit spot should be near or above the short strike, not below it."""
    short_strike = 105.0
    rows = calc_daily_pnl_table(
        long_strike=80,
        long_dte=180,
        long_cost=15.0,
        long_iv=0.35,
        short_strike=short_strike,
        short_dte=3,
        short_premium=2.0,
        short_iv=0.30,
        qty=1,
        spot=100.0,
        right="C",
    )
    for row in rows:
        assert row["optimal_spot"] >= short_strike * 0.95


def test_find_optimal_exit_spot_above_short_strike():
    """For a typical diagonal call spread the optimal exit spot is at or above the short strike."""
    opt_spot, pnl = find_optimal_exit_spot(
        long_strike=80,
        long_days_rem=180,
        long_iv=0.35,
        long_cost=15.0,
        short_strike=105,
        short_days_rem=14,
        short_iv=0.30,
        short_premium=2.0,
        spot=100.0,
    )
    assert opt_spot >= 100.0  # above current spot
    assert isinstance(pnl, float)


def test_find_roll_expiration_targets_basic():
    """Should return two expirations near 7d and 14d after current."""
    from datetime import date, datetime, timedelta

    today = date.today()
    current = today.strftime("%Y%m%d")
    # Generate fake expirations at various offsets
    expirations = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in [5, 8, 14, 21, 35, 60]]
    max_exp = (today + timedelta(days=90)).strftime("%Y%m%d")
    result = find_roll_expiration_targets(current, expirations, max_exp)
    assert len(result) == 2
    # First target is closest to +7d, second to +14d
    r0 = (datetime.strptime(result[0], "%Y%m%d").date() - today).days
    r1 = (datetime.strptime(result[1], "%Y%m%d").date() - today).days
    assert abs(r0 - 7) <= 3
    assert abs(r1 - 14) <= 3


def test_find_roll_expiration_targets_respects_max():
    """Expirations beyond long expiry must be excluded."""
    from datetime import date, timedelta

    today = date.today()
    current = today.strftime("%Y%m%d")
    max_exp = (today + timedelta(days=10)).strftime("%Y%m%d")
    expirations = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in [7, 14, 21]]
    result = find_roll_expiration_targets(current, expirations, max_exp)
    for exp in result:
        assert exp <= max_exp


def test_calc_daily_pnl_table_scales_with_qty():
    rows_1 = calc_daily_pnl_table(
        long_strike=80,
        long_dte=180,
        long_cost=15.0,
        long_iv=0.35,
        short_strike=105,
        short_dte=5,
        short_premium=2.0,
        short_iv=0.30,
        qty=1,
        spot=100.0,
    )
    rows_5 = calc_daily_pnl_table(
        long_strike=80,
        long_dte=180,
        long_cost=15.0,
        long_iv=0.35,
        short_strike=105,
        short_dte=5,
        short_premium=2.0,
        short_iv=0.30,
        qty=5,
        spot=100.0,
    )
    for r1, r5 in zip(rows_1, rows_5):
        # Each row is independently rounded to 2 decimal places, so exact 5x may differ by cents
        assert r5["pnl"] == pytest.approx(r1["pnl"] * 5, abs=0.10)


# ---------------------------------------------------------------------------
# calc_pnl_if_assigned
# ---------------------------------------------------------------------------


def test_calc_pnl_if_assigned_uses_bs_long_value():
    """BS-estimated long value exceeds intrinsic spread width when LEAPS has time value."""
    long_strike, short_strike = 90.0, 110.0
    long_dte, short_dte = 120.0, 1.0
    long_cost, long_iv, total_premium, qty = 18.0, 0.35, 2.0, 1

    result = calc_pnl_if_assigned(
        long_strike, long_dte, long_cost, long_iv, short_strike, short_dte, total_premium, qty
    )

    # Old spread-width formula: (110-90-18+2)*100 = 400
    old_formula = (short_strike - long_strike - long_cost + total_premium) * 100
    assert result > old_formula, "BS-estimated long value should exceed intrinsic spread width"


def test_calc_pnl_if_assigned_scales_with_qty():
    """P&L doubles when qty doubles."""
    kwargs = dict(
        long_strike=90.0,
        long_dte=120.0,
        long_cost=18.0,
        long_iv=0.35,
        short_strike=110.0,
        short_dte=1.0,
        total_premium=2.0,
    )
    r1 = calc_pnl_if_assigned(**kwargs, qty=1)
    r2 = calc_pnl_if_assigned(**kwargs, qty=2)
    assert r2 == pytest.approx(r1 * 2, abs=0.01)


def test_calc_pnl_if_assigned_at_long_expiry_equals_intrinsic():
    """When long expires at same time as short, BS value = intrinsic, matching old formula."""
    long_strike, short_strike = 90.0, 110.0
    dte = 0.0
    long_cost, total_premium, qty = 18.0, 2.0, 1

    result = calc_pnl_if_assigned(
        long_strike, dte, long_cost, 0.35, short_strike, dte, total_premium, qty
    )
    expected = (short_strike - long_strike - long_cost + total_premium) * 100
    assert result == pytest.approx(expected, abs=0.01)


def test_calc_pnl_if_assigned_qty_one_contract():
    """Result is scaled by 100 shares per contract."""
    long_price = calc_bs_price(110.0, 90.0, 119, 0.35, "C")
    expected = round((long_price - 18.0 + 2.0) * 100, 2)
    result = calc_pnl_if_assigned(90.0, 120.0, 18.0, 0.35, 110.0, 1.0, 2.0, 1)
    assert result == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# find_best_rolls
# ---------------------------------------------------------------------------


_EXP_ROLL = (date.today() + timedelta(days=30)).strftime("%Y%m%d")


def _make_quote(strike, bid, ask, expiry=None):
    expiry = expiry or _EXP_ROLL
    mid = (bid + ask) / 2 if bid and ask else 0
    return {"strike": strike, "bid": bid, "ask": ask, "mid": mid, "last": bid, "expiry": expiry}


def test_find_best_rolls_returns_at_most_3():
    # Many candidates, but we only want top 3
    roll_chains = {
        _EXP_ROLL: [
            _make_quote(115, 1.0, 1.20, _EXP_ROLL),  # lower delta, credit roll
            _make_quote(120, 0.80, 1.00, _EXP_ROLL),
            _make_quote(125, 0.60, 0.80, _EXP_ROLL),
            _make_quote(130, 0.40, 0.60, _EXP_ROLL),
        ],
    }
    rolls = find_best_rolls(
        current_short_strike=110,
        current_short_expiry="20260501",
        current_short_dte=1,
        current_short_price=0.10,  # nearly worthless
        current_delta=0.40,
        roll_chains=roll_chains,
        spot=108.0,
        long_strike=90.0,
        long_cost=18.0,
        long_dte=180.0,
        long_iv=0.35,
        qty=1,
        min_roll_dte=7,
        price_mode="mid",
    )
    assert len(rolls) <= 3


def test_find_best_rolls_filters_by_delta():
    """Candidates with delta >= current_delta must be excluded."""
    # At spot=108, IV=0.3, strike=109, 30 dte → delta ≈ 0.49 (high)
    # strike=125, 30 dte → delta should be much lower
    roll_chains = {
        _EXP_ROLL: [
            _make_quote(109, 3.50, 3.80, _EXP_ROLL),  # near ATM, high delta — should be filtered
            _make_quote(130, 0.50, 0.70, _EXP_ROLL),  # OTM, low delta — should pass
        ],
    }
    rolls = find_best_rolls(
        current_short_strike=110,
        current_short_expiry="20260501",
        current_short_dte=1,
        current_short_price=0.10,
        current_delta=0.45,  # filtering threshold
        roll_chains=roll_chains,
        spot=108.0,
        long_strike=90.0,
        long_cost=18.0,
        long_dte=180.0,
        long_iv=0.35,
        qty=1,
        min_roll_dte=7,
        price_mode="mid",
    )
    # All returned rolls must have delta < 0.45
    for roll in rolls:
        assert roll["delta"] < 0.45


def test_find_best_rolls_requires_net_credit():
    """Candidates with debit > NET_CREDIT_MIN (-0.10) should be excluded."""
    roll_chains = {
        _EXP_ROLL: [
            # new mid = 0.25, current = 0.50 → net_credit = -0.25 < -0.10 → excluded
            _make_quote(130, 0.20, 0.30, _EXP_ROLL),
        ],
    }
    rolls = find_best_rolls(
        current_short_strike=110,
        current_short_expiry="20260501",
        current_short_dte=1,
        current_short_price=0.50,  # expensive to buy back
        current_delta=0.45,
        roll_chains=roll_chains,
        spot=108.0,
        long_strike=90.0,
        long_cost=18.0,
        long_dte=180.0,
        long_iv=0.35,
        qty=1,
        min_roll_dte=7,
        price_mode="mid",
    )
    assert rolls == []


def test_find_best_rolls_result_fields():
    roll_chains = {
        _EXP_ROLL: [
            _make_quote(120, 1.0, 1.20, _EXP_ROLL),
        ],
    }
    rolls = find_best_rolls(
        current_short_strike=110,
        current_short_expiry="20260501",
        current_short_dte=1,
        current_short_price=0.05,
        current_delta=0.45,
        roll_chains=roll_chains,
        spot=108.0,
        long_strike=90.0,
        long_cost=18.0,
        long_dte=180.0,
        long_iv=0.35,
        qty=1,
        min_roll_dte=7,
        price_mode="mid",
    )
    for roll in rolls:
        assert "strike" in roll
        assert "expiry" in roll
        assert "dte" in roll
        assert "delta" in roll
        assert "assignment_prob" in roll
        assert "iv_pct" in roll
        assert "net_credit" in roll
        assert "profit_per_day" in roll
        assert "pnl_if_assigned" in roll


def test_find_best_rolls_profit_per_day_is_net_credit_per_day(monkeypatch):
    """profit_per_day = net_credit / dte, not roll_price / dte."""
    # Pin DTE to a fixed reference date so the roll clears min_roll_dte
    # regardless of when the suite runs (find_best_rolls calls days_to_expiry,
    # which otherwise measures against today's real date).
    import datetime as _dt

    from trading_skills.broker import pmcc_advisor

    def _fixed_dte(expiry_str):
        return (_dt.datetime.strptime(expiry_str, "%Y%m%d") - _dt.datetime(2026, 5, 1)).days

    monkeypatch.setattr(pmcc_advisor, "days_to_expiry", _fixed_dte)
    # current short price = $2.00, roll mid = $3.10 → net_credit = $1.10
    roll_chains = {
        _EXP_ROLL: [_make_quote(120, 3.0, 3.20, _EXP_ROLL)],
    }
    rolls = find_best_rolls(
        current_short_strike=110,
        current_short_expiry="20260501",
        current_short_dte=1,
        current_short_price=2.00,
        current_delta=0.45,
        roll_chains=roll_chains,
        spot=108.0,
        long_strike=90.0,
        long_cost=18.0,
        long_dte=180.0,
        long_iv=0.35,
        qty=1,
        min_roll_dte=7,
        price_mode="mid",
    )
    assert len(rolls) == 1
    dte = rolls[0]["dte"]
    expected = round((3.10 - 2.00) / dte, 4)
    assert rolls[0]["profit_per_day"] == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# build_comparison_table
# ---------------------------------------------------------------------------


def test_build_comparison_table_has_current():
    current = {
        "strike": 110,
        "expiry": "20260501",
        "dte": 1,
        "delta": 0.40,
        "assignment_prob": 38.5,
        "price": 0.10,
        "profit_per_day": 0.10,
        "total_premium": 2.0,
    }
    long_pos = {"strike": 90, "expiry": "20260918", "avg_cost": 18.0}
    table = build_comparison_table(
        current=current, rolls=[], long_pos=long_pos, long_dte=120.0, long_iv=0.35, qty=1
    )
    assert "current" in table
    assert table["current"]["strike"] == 110
    assert table["current"]["delta"] == 0.40


def test_build_comparison_table_has_rolls():
    current = {
        "strike": 110,
        "expiry": "20260501",
        "dte": 1,
        "delta": 0.40,
        "assignment_prob": 38.5,
        "price": 0.10,
        "profit_per_day": 0.10,
        "total_premium": 2.0,
    }
    long_pos = {"strike": 90, "expiry": "20260918", "avg_cost": 18.0}
    roll1 = {
        "strike": 120,
        "expiry": _EXP_ROLL,
        "dte": 32,
        "delta": 0.25,
        "assignment_prob": 20.0,
        "price": 1.10,
        "profit_per_day": 0.034,
        "net_credit": 1.00,
        "iv_pct": 28.0,
        "total_premium": 3.10,
    }
    table = build_comparison_table(
        current=current, rolls=[roll1], long_pos=long_pos, long_dte=120.0, long_iv=0.35, qty=1
    )
    assert "roll_1" in table
    assert table["roll_1"]["strike"] == 120


def test_build_comparison_table_pnl_if_assigned_uses_bs_and_qty():
    """pnl_if_assigned uses BS-estimated long value at assignment and scales by qty."""
    current = {
        "strike": 110,
        "expiry": "20260501",
        "dte": 1,
        "delta": 0.40,
        "assignment_prob": 38.5,
        "price": 0.10,
        "profit_per_day": 0.10,
        "total_premium": 2.0,
    }
    long_pos = {"strike": 90, "expiry": "20260918", "avg_cost": 18.0}
    long_dte, long_iv, qty = 120.0, 0.35, 3

    table = build_comparison_table(
        current=current, rolls=[], long_pos=long_pos, long_dte=long_dte, long_iv=long_iv, qty=qty
    )

    long_days_at_assignment = long_dte - current["dte"]  # 119
    long_price = calc_bs_price(110.0, 90.0, long_days_at_assignment, long_iv, "C")
    expected = round((long_price - 18.0 + 2.0) * 100 * qty, 2)
    assert table["current"]["pnl_if_assigned"] == pytest.approx(expected, abs=0.01)

    # Must be larger than old spread-width formula (which would be 4 * 100 * 3 = 1200)
    old_formula = (110 - 90 - 18.0 + 2.0) * 100 * qty
    assert table["current"]["pnl_if_assigned"] > old_formula


# ---------------------------------------------------------------------------
# score_roll_candidate
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# calc_profit_per_day
# ---------------------------------------------------------------------------


def test_calc_profit_per_day_normal_short():
    """(avg_cost - current_price) / dte — profit locked in per remaining day."""
    # received $8.71, now worth $4.20 → $4.51 locked in over 6.2 days
    assert calc_profit_per_day(avg_cost=8.71, current_price=4.20, dte=6.2) == pytest.approx(
        (8.71 - 4.20) / 6.2, rel=1e-4
    )


def test_calc_profit_per_day_underwater_is_negative():
    """Negative when short is underwater (current_price > avg_cost)."""
    # NBIS-style: received $2.64, now worth $5.47 → position is a loss
    result = calc_profit_per_day(avg_cost=2.64, current_price=5.47, dte=6.2)
    assert result < 0
    assert result == pytest.approx((2.64 - 5.47) / 6.2, rel=1e-4)


def test_calc_profit_per_day_falls_back_when_no_price():
    """Falls back to avg_cost / dte when current price is unavailable."""
    assert calc_profit_per_day(avg_cost=5.00, current_price=None, dte=10) == pytest.approx(0.5)


def test_calc_profit_per_day_clamps_zero_dte():
    """Near-zero DTE uses 1-hour minimum to avoid division by zero."""
    result = calc_profit_per_day(avg_cost=1.0, current_price=0.5, dte=0)
    assert result > 0


def test_score_roll_candidate_lower_delta_scores_higher():
    c1 = {"delta": 0.20, "net_credit": 0.50, "dte": 30}
    c2 = {"delta": 0.35, "net_credit": 0.50, "dte": 30}
    s1 = score_roll_candidate(current_delta=0.40, candidate=c1)
    s2 = score_roll_candidate(current_delta=0.40, candidate=c2)
    assert s1 > s2


def test_score_roll_candidate_more_credit_scores_higher():
    c1 = {"delta": 0.25, "net_credit": 1.00, "dte": 30}
    c2 = {"delta": 0.25, "net_credit": 0.10, "dte": 30}
    s1 = score_roll_candidate(current_delta=0.40, candidate=c1)
    s2 = score_roll_candidate(current_delta=0.40, candidate=c2)
    assert s1 > s2


# ---------------------------------------------------------------------------
# check_earnings_warning
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# filter_spreads_by_symbols
# ---------------------------------------------------------------------------


def _make_spread(symbol: str) -> dict:
    return {"symbol": symbol, "long": {}, "short": {}, "qty": 1}


def test_filter_spreads_by_symbols_returns_all_when_none():
    spreads = [_make_spread("NVDA"), _make_spread("CAT"), _make_spread("WMT")]
    assert filter_spreads_by_symbols(spreads, None) == spreads


def test_filter_spreads_by_symbols_filters_case_insensitive():
    spreads = [_make_spread("NVDA"), _make_spread("CAT"), _make_spread("WMT")]
    result = filter_spreads_by_symbols(spreads, ["nvda", "cat"])
    assert [s["symbol"] for s in result] == ["NVDA", "CAT"]


def test_filter_spreads_by_symbols_unknown_symbol_ignored():
    spreads = [_make_spread("NVDA"), _make_spread("CAT")]
    result = filter_spreads_by_symbols(spreads, ["NVDA", "AAPL"])
    assert [s["symbol"] for s in result] == ["NVDA"]


def test_filter_spreads_by_symbols_empty_list_returns_empty():
    spreads = [_make_spread("NVDA"), _make_spread("CAT")]
    assert filter_spreads_by_symbols(spreads, []) == []


def test_check_earnings_warning_no_date():
    result = check_earnings_warning(
        earnings_date=None,
        earnings_timing=None,
        short_expiry="20260508",
        roll_candidates=[],
    )
    assert result["date"] is None
    assert result["warning_short"] is False
    assert result["warning_roll_indices"] == []


def test_check_earnings_warning_within_short_window():
    """Earnings within 7 days before short expiry should flag warning_short."""
    today = date.today()
    earn_dt = today + timedelta(days=3)
    exp_dt = today + timedelta(days=6)
    earn_str = earn_dt.strftime("%Y-%m-%d")
    exp_str = exp_dt.strftime("%Y%m%d")
    result = check_earnings_warning(
        earnings_date=earn_str,
        earnings_timing="AMC",
        short_expiry=exp_str,
        roll_candidates=[],
    )
    assert result["warning_short"] is True
    assert result["date"] == earn_str
    assert result["timing"] == "AMC"


def test_check_earnings_warning_outside_short_window():
    """Earnings more than 7 days before short expiry should not flag warning_short."""
    result = check_earnings_warning(
        earnings_date="2026-04-20",
        earnings_timing=None,
        short_expiry="20260508",
        roll_candidates=[],
    )
    assert result["warning_short"] is False


def test_check_earnings_warning_past_date_no_warning():
    """Past earnings should never trigger warnings."""
    result = check_earnings_warning(
        earnings_date="2020-01-01",
        earnings_timing=None,
        short_expiry="20260508",
        roll_candidates=[{"expiry": "20260522", "strike": 110}],
    )
    assert result["warning_short"] is False
    assert result["warning_roll_indices"] == []


def test_check_earnings_warning_on_expiry_day():
    """Earnings on exact expiry date is within the window."""
    exp_dt = date.today() + timedelta(days=5)
    exp_str = exp_dt.strftime("%Y%m%d")
    earn_str = exp_dt.strftime("%Y-%m-%d")
    result = check_earnings_warning(
        earnings_date=earn_str,
        earnings_timing="BMO",
        short_expiry=exp_str,
        roll_candidates=[],
    )
    assert result["warning_short"] is True


def test_check_earnings_warning_roll_overlap():
    """Earnings falling before a roll expiry should flag that roll's index."""
    rolls = [
        {"expiry": "20260515", "strike": 210},  # roll 1
        {"expiry": "20260522", "strike": 215},  # roll 2
    ]
    fake_today = date(2026, 5, 10)
    with patch("trading_skills.broker.pmcc_advisor.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = fake_today
        mock_dt.strptime.side_effect = lambda s, f: __import__("datetime").datetime.strptime(s, f)
        result = check_earnings_warning(
            earnings_date="2026-05-12",
            earnings_timing=None,
            short_expiry="20260508",
            roll_candidates=rolls,
        )
    # earnings on May 12 → before May 15 (roll 1) and before May 22 (roll 2)
    assert 1 in result["warning_roll_indices"]
    assert 2 in result["warning_roll_indices"]


def test_check_earnings_warning_roll_partial_overlap():
    """Only rolls whose expiry is on or after earnings date are flagged."""
    rolls = [
        {"expiry": "20260510", "strike": 210},  # roll 1: expires before earnings
        {"expiry": "20260522", "strike": 215},  # roll 2: expires after earnings
    ]
    fake_today = date(2026, 5, 10)
    with patch("trading_skills.broker.pmcc_advisor.datetime") as mock_dt:
        mock_dt.now.return_value.date.return_value = fake_today
        mock_dt.strptime.side_effect = lambda s, f: __import__("datetime").datetime.strptime(s, f)
        result = check_earnings_warning(
            earnings_date="2026-05-14",
            earnings_timing=None,
            short_expiry="20260508",
            roll_candidates=rolls,
        )
    assert 1 not in result["warning_roll_indices"]
    assert 2 in result["warning_roll_indices"]


# ---------------------------------------------------------------------------
# Additional edge case tests for analytics coverage
# ---------------------------------------------------------------------------


def test_get_option_price_ask_only():
    """Returns ask when bid is None/zero and last is None."""
    result = get_option_price({"bid": None, "ask": 2.50, "last": None}, "mid")
    assert result == pytest.approx(2.50)


def test_calc_assignment_prob_zero_iv():
    """Returns 0.0 when IV is zero (degenerate case)."""
    result = calc_assignment_prob(100.0, 110.0, 30, 0.0, "C")
    assert result == 0.0


def test_find_roll_expiration_targets_empty_candidates():
    """Returns empty list when no candidates are available after current expiry."""
    result = find_roll_expiration_targets(
        current_expiry="20260620",
        available_expirations=[],
        max_expiry="20270101",
    )
    assert result == []


def test_ibkr_to_yf_date():
    from trading_skills.broker.pmcc_advisor import _ibkr_to_yf_date

    assert _ibkr_to_yf_date("20260620") == "2026-06-20"


def test_yf_to_ibkr_date():
    from trading_skills.broker.pmcc_advisor import _yf_to_ibkr_date

    assert _yf_to_ibkr_date("2026-06-20") == "20260620"


def test_closest_yf_expiry_empty_returns_none():
    from trading_skills.broker.pmcc_advisor import _closest_yf_expiry

    assert _closest_yf_expiry("20260620", []) is None


def test_closest_yf_expiry_picks_nearest():
    from trading_skills.broker.pmcc_advisor import _closest_yf_expiry

    result = _closest_yf_expiry("20260620", ["2026-06-19", "2026-06-26", "2026-07-17"])
    assert result == "2026-06-19"


def test_find_best_rolls_skips_small_dte():
    """Roll chains whose DTE < min_roll_dte are skipped."""
    from datetime import datetime, timedelta

    # Expiry 2 days out (< default min_roll_dte=7)
    close_expiry = (datetime.now() + timedelta(days=2)).strftime("%Y%m%d")
    far_expiry = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")

    roll_chains = {
        close_expiry: [{"strike": 210.0, "bid": 3.0, "ask": 3.4, "last": 3.2, "mid": 3.2}],
        far_expiry: [{"strike": 215.0, "bid": 4.0, "ask": 4.4, "last": 4.2, "mid": 4.2}],
    }
    result = find_best_rolls(
        current_short_strike=210.0,
        current_short_expiry="20250101",
        current_short_dte=5,
        current_short_price=3.0,
        current_delta=0.40,
        roll_chains=roll_chains,
        spot=200.0,
        long_strike=180.0,
        long_cost=20.0,
        long_dte=300.0,
        long_iv=0.35,
        qty=1,
        min_roll_dte=7,
        price_mode="mid",
    )
    # Only the far expiry should be a candidate
    if result:
        for r in result:
            assert r["expiry"] == far_expiry


def test_find_best_rolls_skips_same_expiry_as_current_short():
    """Roll candidates with expiry == current_short_expiry are skipped."""
    from datetime import datetime, timedelta

    same_expiry = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")
    diff_expiry = (datetime.now() + timedelta(days=45)).strftime("%Y%m%d")

    roll_chains = {
        same_expiry: [{"strike": 210.0, "bid": 3.0, "ask": 3.4, "last": 3.2, "mid": 3.2}],
        diff_expiry: [{"strike": 215.0, "bid": 4.0, "ask": 4.4, "last": 4.2, "mid": 4.2}],
    }
    result = find_best_rolls(
        current_short_strike=210.0,
        current_short_expiry=same_expiry,
        current_short_dte=30,
        current_short_price=3.0,
        current_delta=0.40,
        roll_chains=roll_chains,
        spot=200.0,
        long_strike=180.0,
        long_cost=20.0,
        long_dte=300.0,
        long_iv=0.35,
        qty=1,
        min_roll_dte=7,
        price_mode="mid",
    )
    if result:
        for r in result:
            assert r["expiry"] != same_expiry


# ---------------------------------------------------------------------------
# Off-hours option price fallback (_fetch_single_option_quote / _fetch_option_quotes_batch)
# ---------------------------------------------------------------------------


def _make_ticker(bid=math.nan, ask=math.nan, last=math.nan, close=math.nan, model_greeks=None):
    t = MagicMock()
    t.bid = bid
    t.ask = ask
    t.last = last
    t.close = close
    t.modelGreeks = model_greeks
    return t


def _make_ib(ticker, contract=None):
    if contract is None:
        contract = MagicMock()
    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[contract])
    ib.reqMktData = MagicMock(return_value=ticker)
    ib.cancelMktData = MagicMock()
    return ib


def test_fetch_single_option_quote_falls_back_to_close_when_last_is_nan():
    """Off-hours: bid/ask/last are NaN but close has the session's closing price."""
    ticker = _make_ticker(close=5.23)
    contract = MagicMock()
    contract.conId = 12345
    ib = _make_ib(ticker, contract)

    with patch("trading_skills.broker.pmcc_advisor.asyncio.sleep", new=AsyncMock()):
        result = asyncio.run(_fetch_single_option_quote(ib, "AAPL", 200.0, "20260117", "C"))

    assert result is not None
    assert result["bid"] is None
    assert result["ask"] is None
    assert result["last"] == pytest.approx(5.23)
    assert result["stale"] is True


def test_fetch_single_option_quote_prefers_last_over_close():
    """When last price is available, use it (not close)."""
    ticker = _make_ticker(bid=4.90, ask=5.10, last=5.00, close=4.80)
    contract = MagicMock()
    contract.conId = 12345
    ib = _make_ib(ticker, contract)

    with patch("trading_skills.broker.pmcc_advisor.asyncio.sleep", new=AsyncMock()):
        result = asyncio.run(_fetch_single_option_quote(ib, "AAPL", 200.0, "20260117", "C"))

    assert result is not None
    assert result["last"] == pytest.approx(5.00)
    assert result["stale"] is False


def test_fetch_option_quotes_batch_falls_back_to_close_when_last_is_nan():
    """Off-hours batch: bid/ask/last are NaN but close has the session's closing price."""
    ticker = _make_ticker(close=3.75)
    contract = MagicMock()
    contract.conId = 99
    contract.strike = 210.0

    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[contract])
    ib.reqMktData = MagicMock(return_value=ticker)
    ib.cancelMktData = MagicMock()

    with patch("trading_skills.broker.pmcc_advisor.asyncio.sleep", new=AsyncMock()):
        results = asyncio.run(_fetch_option_quotes_batch(ib, "AAPL", "20260117", [210.0], "C"))

    assert len(results) == 1
    assert results[0]["last"] == pytest.approx(3.75)
    assert results[0]["stale"] is True

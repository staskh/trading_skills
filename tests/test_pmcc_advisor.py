# ABOUTME: Unit tests for PMCC advisor analytics functions.
# ABOUTME: All tests run without IBKR dependency — pure calculation coverage.


from datetime import date, timedelta

import pytest

from trading_skills.broker.pmcc_advisor import (
    build_comparison_table,
    calc_assignment_prob,
    calc_bs_price,
    calc_daily_pnl_table,
    calc_delta,
    calc_iv,
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
# find_best_rolls
# ---------------------------------------------------------------------------


def _make_quote(strike, bid, ask, expiry="20260601"):
    mid = (bid + ask) / 2 if bid and ask else 0
    return {"strike": strike, "bid": bid, "ask": ask, "mid": mid, "last": bid, "expiry": expiry}


def test_find_best_rolls_returns_at_most_3():
    # Many candidates, but we only want top 3
    roll_chains = {
        "20260601": [
            _make_quote(115, 1.0, 1.20, "20260601"),  # lower delta, credit roll
            _make_quote(120, 0.80, 1.00, "20260601"),
            _make_quote(125, 0.60, 0.80, "20260601"),
            _make_quote(130, 0.40, 0.60, "20260601"),
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
        min_roll_dte=7,
        price_mode="mid",
    )
    assert len(rolls) <= 3


def test_find_best_rolls_filters_by_delta():
    """Candidates with delta >= current_delta must be excluded."""
    # At spot=108, IV=0.3, strike=109, 30 dte → delta ≈ 0.49 (high)
    # strike=125, 30 dte → delta should be much lower
    roll_chains = {
        "20260601": [
            _make_quote(109, 3.50, 3.80, "20260601"),  # near ATM, high delta — should be filtered
            _make_quote(130, 0.50, 0.70, "20260601"),  # OTM, low delta — should pass
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
        min_roll_dte=7,
        price_mode="mid",
    )
    # All returned rolls must have delta < 0.45
    for roll in rolls:
        assert roll["delta"] < 0.45


def test_find_best_rolls_requires_net_credit():
    """Candidates with debit > NET_CREDIT_MIN (-0.10) should be excluded."""
    roll_chains = {
        "20260601": [
            # new mid = 0.25, current = 0.50 → net_credit = -0.25 < -0.10 → excluded
            _make_quote(130, 0.20, 0.30, "20260601"),
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
        min_roll_dte=7,
        price_mode="mid",
    )
    assert rolls == []


def test_find_best_rolls_result_fields():
    roll_chains = {
        "20260601": [
            _make_quote(120, 1.0, 1.20, "20260601"),
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


def test_find_best_rolls_profit_per_day_is_net_credit_per_day():
    """profit_per_day = net_credit / dte, not roll_price / dte."""
    # current short price = $2.00, roll mid = $3.10 → net_credit = $1.10
    roll_chains = {
        "20260601": [_make_quote(120, 3.0, 3.20, "20260601")],
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
    table = build_comparison_table(current=current, rolls=[], long_pos=long_pos)
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
        "expiry": "20260601",
        "dte": 32,
        "delta": 0.25,
        "assignment_prob": 20.0,
        "price": 1.10,
        "profit_per_day": 0.034,
        "net_credit": 1.00,
        "iv_pct": 28.0,
        "total_premium": 3.10,
    }
    table = build_comparison_table(current=current, rolls=[roll1], long_pos=long_pos)
    assert "roll_1" in table
    assert table["roll_1"]["strike"] == 120


def test_build_comparison_table_pnl_if_assigned():
    """P&L if assigned = (short_strike - long_strike - long_cost + total_premium) * qty * 100."""
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
    long_pos = {"strike": 90, "expiry": "20260918", "avg_cost": 18.0, "qty": 1}
    table = build_comparison_table(current=current, rolls=[], long_pos=long_pos)
    # (110 - 90 - 18.0 + 2.0) * 1 * 100 = 4.0 * 100 = 400
    assert table["current"]["pnl_if_assigned"] == pytest.approx(400.0)


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
    result = check_earnings_warning(
        earnings_date="2026-05-14",
        earnings_timing=None,
        short_expiry="20260508",
        roll_candidates=rolls,
    )
    assert 1 not in result["warning_roll_indices"]
    assert 2 in result["warning_roll_indices"]

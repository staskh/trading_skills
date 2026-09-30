# ABOUTME: Unit tests for the operational PMCC bot pure logic.
# ABOUTME: Margin gate, exit decay trigger, order sizing/tagging — no IBKR dependency.

from trading_skills.broker.pmcc_bot import (
    build_entry_plan,
    entry_cost_usd,
    order_ref_for,
    select_entries,
    short_decay_pct,
    should_close_short,
)


def _candidate(symbol, score, net_debit, ann_yield=100.0, leaps_strike=100.0, short_strike=120.0):
    return {
        "symbol": symbol,
        "pmcc_score": score,
        "metrics": {"net_debit": net_debit, "annual_yield_est_pct": ann_yield},
        "leaps": {
            "expiry": "2027-03-19",
            "strike": leaps_strike,
            "mid": net_debit + 1.0,
            "delta": 0.8,
        },
        "short": {"expiry": "2026-06-17", "strike": short_strike, "mid": 1.0, "delta": 0.2},
    }


# ---- entry_cost_usd ----


def test_entry_cost_is_net_debit_times_100():
    c = _candidate("AAPL", 12.5, net_debit=54.15)
    assert entry_cost_usd(c) == 5415.0


def test_entry_cost_zero_when_missing_metrics():
    assert entry_cost_usd({"symbol": "X"}) == 0.0


# ---- order_ref_for ----


def test_order_ref_tag_format():
    assert order_ref_for("aapl", "2026-06-17") == "BOT_PMCC_AAPL_20260617"


# ---- select_entries: ranking, top_n, margin gate, min_score ----


def test_select_picks_highest_score_first():
    cands = [
        _candidate("LOW", 8.0, 10.0),
        _candidate("HIGH", 13.0, 10.0),
        _candidate("MID", 11.0, 10.0),
    ]
    selected, _ = select_entries(cands, available_funds=1_000_000, top_n=3)
    assert [s["symbol"] for s in selected] == ["HIGH", "MID", "LOW"]


def test_select_respects_top_n():
    cands = [_candidate(f"S{i}", 10.0 + i, 10.0) for i in range(5)]
    selected, skipped = select_entries(cands, available_funds=1_000_000, top_n=3)
    assert len(selected) == 3
    assert all("beyond top-3" in s["skip_reason"] for s in skipped)


def test_margin_gate_skips_when_insufficient_funds():
    # Two candidates at $5,000 each; only $6,000 available -> second skipped.
    cands = [_candidate("A", 13.0, 50.0), _candidate("B", 12.0, 50.0)]
    selected, skipped = select_entries(cands, available_funds=6_000, top_n=3)
    assert [s["symbol"] for s in selected] == ["A"]
    assert len(skipped) == 1
    assert skipped[0]["symbol"] == "B"
    assert "insufficient funds" in skipped[0]["skip_reason"]


def test_margin_gate_allows_when_exactly_fits():
    cands = [_candidate("A", 13.0, 50.0), _candidate("B", 12.0, 50.0)]
    selected, skipped = select_entries(cands, available_funds=10_000, top_n=3)
    assert [s["symbol"] for s in selected] == ["A", "B"]
    assert skipped == []


def test_min_score_filters_out_low_candidates():
    cands = [_candidate("A", 13.0, 10.0), _candidate("B", 5.0, 10.0)]
    selected, _ = select_entries(cands, available_funds=1_000_000, top_n=3, min_score=10.0)
    assert [s["symbol"] for s in selected] == ["A"]


def test_selected_entries_carry_entry_cost():
    cands = [_candidate("A", 13.0, 50.0)]
    selected, _ = select_entries(cands, available_funds=1_000_000)
    assert selected[0]["entry_cost"] == 5000.0


# ---- short_decay_pct / should_close_short ----


def test_decay_pct_full_when_short_worthless():
    assert short_decay_pct(2.0, 0.0) == 1.0


def test_decay_pct_zero_when_unchanged():
    assert short_decay_pct(2.0, 2.0) == 0.0


def test_decay_pct_negative_when_short_moves_against():
    assert short_decay_pct(2.0, 3.0) == -0.5


def test_decay_pct_guards_zero_premium():
    assert short_decay_pct(0.0, 1.0) == 0.0


def test_should_close_at_threshold():
    # 70% decayed: premium 2.0 -> now 0.60 means 70% captured.
    assert should_close_short(2.0, 0.60, threshold=0.70) is True


def test_should_not_close_below_threshold():
    assert should_close_short(2.0, 0.80, threshold=0.70) is False


# ---- build_entry_plan ----


def test_entry_plan_legs_and_limit():
    c = _candidate("NVDA", 12.5, net_debit=56.15, leaps_strike=170.0, short_strike=222.5)
    plan = build_entry_plan(c)
    assert plan["symbol"] == "NVDA"
    assert plan["order_ref"] == "BOT_PMCC_NVDA_20260617"
    assert plan["limit_price"] == 56.15
    assert plan["entry_cost"] == 5615.0
    buy, sell = plan["legs"]
    assert buy["action"] == "BUY" and buy["strike"] == 170.0
    assert sell["action"] == "SELL" and sell["strike"] == 222.5

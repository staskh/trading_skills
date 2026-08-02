# ABOUTME: Tests for consolidating executions into legs and pairing them into spreads.
# ABOUTME: Covers the happy path, cross-date settlement, and every rejection guard.

from trading_skills.broker.spreads import (
    REASON_MULTI_STRIKE,
    REASON_NO_CLOSE,
    REASON_NO_OPEN,
    REASON_NO_OPENCLOSE,
    REASON_ONE_SIDED,
    REASON_RATIO,
    consolidate_legs,
    group_into_spreads,
)


def ex(
    *,
    dt,
    strike,
    right="C",
    side="SLD",
    oc="O",
    qty=1.0,
    price=1.0,
    pnl=0.0,
    comm=-1.0,
    book=False,
    symbol="NDX",
    account="U1",
    expiry="20260727",
):
    """Build one normalized execution dict."""
    return {
        "account": account,
        "symbol": symbol,
        "secType": "OPT",
        "side": side,
        "quantity": qty,
        "price": price,
        "avgPrice": price,
        "datetime": dt,
        "commission": comm,
        "realizedPnL": pnl,
        "strike": strike,
        "expiry": expiry,
        "right": right,
        "openClose": oc,
        "bookTrade": book,
        "multiplier": 100.0,
    }


def test_consolidate_merges_partial_fills_into_one_leg():
    """A single order split across venues collapses to one quantity-weighted leg."""
    fills = [
        ex(dt="2026-07-27T09:53:49", strike=28560, qty=3, price=11.0, comm=-3.0),
        ex(dt="2026-07-27T09:53:51", strike=28560, qty=2, price=11.5, comm=-2.0),
        ex(dt="2026-07-27T09:53:55", strike=28560, qty=5, price=11.4, comm=-5.0),
    ]
    legs = consolidate_legs(fills)

    assert len(legs) == 1
    leg = legs[0]
    assert leg["quantity"] == 10
    assert leg["avgPrice"] == round((3 * 11.0 + 2 * 11.5 + 5 * 11.4) / 10, 4)
    assert leg["commission"] == -10.0


def test_consolidate_keeps_distinct_minutes_separate():
    """Fills a minute apart are separate orders and must not be merged."""
    fills = [
        ex(dt="2026-07-28T12:17:00", strike=28100, qty=11),
        ex(dt="2026-07-28T12:19:00", strike=28100, qty=4),
    ]
    assert len(consolidate_legs(fills)) == 2


def test_groups_clean_vertical_with_metrics():
    """A closed bear call spread produces correct credit, width, risk and RoR."""
    fills = [
        ex(dt="2026-07-27T09:53:00", strike=28560, side="SLD", oc="O", qty=10, price=11.30),
        ex(dt="2026-07-27T09:53:00", strike=28625, side="BOT", oc="O", qty=10, price=5.60),
        ex(
            dt="2026-07-27T11:13:00",
            strike=28560,
            side="BOT",
            oc="C",
            qty=10,
            price=2.00,
            pnl=9275.08,
        ),
        ex(
            dt="2026-07-27T11:13:00",
            strike=28625,
            side="SLD",
            oc="C",
            qty=10,
            price=1.55,
            pnl=-4074.92,
        ),
    ]
    out = group_into_spreads(fills)

    assert out["warnings"] == []
    assert len(out["spreads"]) == 1
    s = out["spreads"][0]
    assert s["type"] == "Bear call"
    assert s["short_strike"] == 28560
    assert s["long_strike"] == 28625
    assert s["width"] == 65
    assert s["lots"] == 10
    assert s["credit"] == 5.70
    assert s["max_credit"] == 5700.0
    assert s["max_risk"] == round((65 - 5.70) * 10 * 100, 2)
    assert s["realizedPnL"] == 5200.16
    assert s["same_day"] is True
    assert s["settled_at_expiry"] is False


def test_bull_put_named_from_right_and_credit():
    """A short put vertical opened for a credit is a bull put."""
    fills = [
        ex(dt="2026-07-29T10:57:00", strike=26875, right="P", side="SLD", oc="O", price=16.04),
        ex(dt="2026-07-29T10:57:00", strike=26775, right="P", side="BOT", oc="O", price=9.04),
        ex(dt="2026-07-29T14:13:00", strike=26875, right="P", side="BOT", oc="C", price=1.79),
        ex(dt="2026-07-29T14:13:00", strike=26775, right="P", side="SLD", oc="C", price=1.15),
    ]
    s = group_into_spreads(fills)["spreads"][0]
    assert s["type"] == "Bull put"
    assert s["credit"] == 7.00


def test_settlement_on_later_date_still_pairs_with_its_open():
    """Regression: keying on trade date orphaned next-day settlement and dropped its P&L."""
    fills = [
        ex(
            dt="2026-05-14T10:52:00",
            strike=30200,
            side="SLD",
            oc="O",
            qty=7,
            price=4.66,
            expiry="20260515",
        ),
        ex(
            dt="2026-05-14T10:52:00",
            strike=30400,
            side="BOT",
            oc="O",
            qty=7,
            price=1.45,
            expiry="20260515",
        ),
        ex(
            dt="2026-05-15T16:20:00",
            strike=30200,
            side="BOT",
            oc="C",
            qty=7,
            price=0.0,
            pnl=3252.61,
            comm=0.0,
            book=True,
            expiry="20260515",
        ),
        ex(
            dt="2026-05-15T16:20:00",
            strike=30400,
            side="SLD",
            oc="C",
            qty=7,
            price=0.0,
            pnl=-1024.39,
            comm=0.0,
            book=True,
            expiry="20260515",
        ),
    ]
    out = group_into_spreads(fills)

    assert len(out["spreads"]) == 1
    s = out["spreads"][0]
    assert s["entry_date"] == "2026-05-14"
    assert s["exit_date"] == "2026-05-15"
    assert s["realizedPnL"] == 2228.22
    assert s["settled_at_expiry"] is True
    assert s["same_day"] is False


def test_iron_condor_splits_into_two_verticals():
    """Both wings of a condor group independently by right."""
    fills = [
        ex(dt="2026-07-30T09:35:00", strike=28110, right="C", side="SLD", oc="O", price=12.25),
        ex(dt="2026-07-30T09:35:00", strike=28180, right="C", side="BOT", oc="O", price=6.95),
        ex(dt="2026-07-30T16:20:00", strike=28110, right="C", side="BOT", oc="C", price=0.0),
        ex(dt="2026-07-30T16:20:00", strike=28180, right="C", side="SLD", oc="C", price=0.0),
        ex(
            dt="2026-07-30T11:50:00",
            strike=27370,
            right="P",
            side="SLD",
            oc="O",
            price=4.81,
            expiry="20260730",
        ),
        ex(
            dt="2026-07-30T11:50:00",
            strike=27300,
            right="P",
            side="BOT",
            oc="O",
            price=3.37,
            expiry="20260730",
        ),
        ex(
            dt="2026-07-30T14:52:00",
            strike=27370,
            right="P",
            side="BOT",
            oc="C",
            price=0.68,
            expiry="20260730",
        ),
        ex(
            dt="2026-07-30T14:52:00",
            strike=27300,
            right="P",
            side="SLD",
            oc="C",
            price=0.48,
            expiry="20260730",
        ),
    ]
    out = group_into_spreads(fills)
    assert len(out["spreads"]) == 2
    assert {s["type"] for s in out["spreads"]} == {"Bear call", "Bull put"}


def test_ratio_spread_is_rejected_not_averaged():
    """Unequal short/long quantity must not be forced into a vertical."""
    fills = [
        ex(dt="2026-07-27T10:00:00", strike=28560, side="SLD", oc="O", qty=10),
        ex(dt="2026-07-27T10:00:00", strike=28625, side="BOT", oc="O", qty=5),
        ex(dt="2026-07-27T11:00:00", strike=28560, side="BOT", oc="C", qty=10),
        ex(dt="2026-07-27T11:00:00", strike=28625, side="SLD", oc="C", qty=5),
    ]
    out = group_into_spreads(fills)
    assert out["spreads"] == []
    assert any(REASON_RATIO in w for w in out["warnings"])
    assert len(out["ungrouped"]) == 4


def test_three_open_strikes_rejected_not_fused():
    """Two verticals on the same expiry+right would fuse into a bogus average strike."""
    fills = [
        ex(dt="2026-07-27T10:00:00", strike=28560, side="SLD", oc="O"),
        ex(dt="2026-07-27T10:00:00", strike=28625, side="BOT", oc="O"),
        ex(dt="2026-07-27T10:05:00", strike=28700, side="BOT", oc="O"),
        ex(dt="2026-07-27T11:00:00", strike=28560, side="BOT", oc="C"),
    ]
    out = group_into_spreads(fills)
    assert out["spreads"] == []
    assert any(REASON_MULTI_STRIKE in w for w in out["warnings"])


def test_single_leg_rejected():
    """A naked short with no long wing is not a vertical."""
    fills = [
        ex(dt="2026-07-27T10:00:00", strike=28560, side="SLD", oc="O"),
        ex(dt="2026-07-27T11:00:00", strike=28560, side="BOT", oc="C"),
    ]
    out = group_into_spreads(fills)
    assert out["spreads"] == []
    assert any(REASON_ONE_SIDED in w for w in out["warnings"])


def test_close_without_open_rejected():
    """Legs closing a position opened before the window cannot form a spread."""
    fills = [
        ex(dt="2026-07-27T11:00:00", strike=28560, side="BOT", oc="C"),
        ex(dt="2026-07-27T11:00:00", strike=28625, side="SLD", oc="C"),
    ]
    out = group_into_spreads(fills)
    assert out["spreads"] == []
    assert any(REASON_NO_OPEN in w for w in out["warnings"])


def test_open_without_close_rejected():
    """A position still open has no realized result to report."""
    fills = [
        ex(dt="2026-07-27T10:00:00", strike=28560, side="SLD", oc="O"),
        ex(dt="2026-07-27T10:00:00", strike=28625, side="BOT", oc="O"),
    ]
    out = group_into_spreads(fills)
    assert out["spreads"] == []
    assert any(REASON_NO_CLOSE in w for w in out["warnings"])


def test_missing_openclose_reports_unsupported_source():
    """The live API path yields openClose=None and must say so, not guess."""
    fills = [
        ex(dt="2026-07-27T10:00:00", strike=28560, side="SLD", oc=None),
        ex(dt="2026-07-27T10:00:00", strike=28625, side="BOT", oc=None),
    ]
    out = group_into_spreads(fills)
    assert out["spreads"] == []
    assert out["warnings"] == [REASON_NO_OPENCLOSE]
    assert len(out["ungrouped"]) == 2


def test_odd_openclose_value_rejects_only_its_group():
    """IBKR's 'C;O' on one group must not discard a clean spread in another."""
    good = [
        ex(dt="2026-07-27T10:00:00", strike=28560, right="C", side="SLD", oc="O", price=11.30),
        ex(dt="2026-07-27T10:00:00", strike=28625, right="C", side="BOT", oc="O", price=5.60),
        ex(dt="2026-07-27T11:00:00", strike=28560, right="C", side="BOT", oc="C", price=2.00),
        ex(dt="2026-07-27T11:00:00", strike=28625, right="C", side="SLD", oc="C", price=1.55),
    ]
    odd = [
        ex(dt="2026-07-27T10:00:00", strike=27000, right="P", side="SLD", oc="C;O"),
        ex(dt="2026-07-27T10:00:00", strike=26900, right="P", side="BOT", oc="C;O"),
    ]
    out = group_into_spreads(good + odd)

    assert len(out["spreads"]) == 1
    assert out["spreads"][0]["type"] == "Bear call"
    assert any(REASON_NO_OPENCLOSE in w for w in out["warnings"])


def test_non_option_legs_skipped():
    """Stock fills are not spread-eligible and are set aside, not dropped silently."""
    stock = {
        "account": "U1",
        "symbol": "LUNR",
        "secType": "STK",
        "side": "BOT",
        "quantity": 1000,
        "price": 32.61,
        "datetime": "2026-05-11T16:26:11",
        "commission": -2.4,
        "realizedPnL": 0.0,
        "right": None,
        "strike": None,
        "expiry": None,
        "openClose": "O",
    }
    out = group_into_spreads([stock])
    assert out["spreads"] == []
    assert len(out["ungrouped"]) == 1
    assert any("non-option" in w for w in out["warnings"])


def test_leg_pnl_keeps_full_precision_so_totals_reconcile():
    """Rounding each leg then summing drifts cents across many legs; round once instead."""
    fills = []
    for i in range(50):
        fills.append(
            ex(dt=f"2026-07-27T10:{i:02d}:00", strike=28560, side="SLD", oc="O", price=5.0)
        )
        fills.append(
            ex(dt=f"2026-07-27T10:{i:02d}:00", strike=28625, side="BOT", oc="O", price=1.0)
        )
        fills.append(
            ex(
                dt=f"2026-07-27T11:{i:02d}:00",
                strike=28560,
                side="BOT",
                oc="C",
                price=0.0,
                pnl=1.005,
            )
        )
        fills.append(
            ex(
                dt=f"2026-07-27T11:{i:02d}:00",
                strike=28625,
                side="SLD",
                oc="C",
                price=0.0,
                pnl=-0.335,
            )
        )

    exec_total = round(sum(f["realizedPnL"] for f in fills), 2)
    out = group_into_spreads(fills)
    spread_total = round(sum(s["realizedPnL"] for s in out["spreads"]), 2)
    ungrouped_total = round(sum(x["realizedPnL"] for x in out["ungrouped"]), 2)

    assert abs(exec_total - (spread_total + ungrouped_total)) < 0.01


def test_multiplier_other_than_100_used_for_risk():
    """Risk and credit scale by the contract multiplier, not a hardcoded 100."""
    fills = [
        ex(dt="2026-07-27T10:00:00", strike=100, side="SLD", oc="O", qty=1, price=5.0),
        ex(dt="2026-07-27T10:00:00", strike=110, side="BOT", oc="O", qty=1, price=1.0),
        ex(dt="2026-07-27T11:00:00", strike=100, side="BOT", oc="C", qty=1, price=0.0),
        ex(dt="2026-07-27T11:00:00", strike=110, side="SLD", oc="C", qty=1, price=0.0),
    ]
    for f in fills:
        f["multiplier"] = 20.0

    s = group_into_spreads(fills)["spreads"][0]
    assert s["max_credit"] == 4.0 * 1 * 20
    assert s["max_risk"] == round((10 - 4.0) * 1 * 20, 2)

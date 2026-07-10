# ABOUTME: Tests for the 0DTE credit-spread finder.
# ABOUTME: Pure scoring/construction tests run offline; IB-backed tests are manual.

import asyncio
from datetime import datetime

import pytest

from trading_skills.broker.zero_dte import (
    NY,
    _maybe_execute,
    _resolve_quote,
    assess_timing,
    build_iron_condors,
    build_verticals,
    event_guidance,
    find_0dte_spreads,
    get_0dte_expiries,
    pop_short,
    rank_candidates,
    resolve_entry_delta,
    resolve_underlying,
)


def _opt(strike, mid, delta=None, iv=None, right="C"):
    """Build a minimal option-quote dict as the fetch layer produces."""
    return {
        "strike": strike,
        "right": right,
        "bid": round(mid - 0.05, 2),
        "ask": round(mid + 0.05, 2),
        "mid": mid,
        "delta": delta,
        "iv": iv,
    }


# --------------------------------------------------------------------------- #
# Intraday timing & event guidance
# --------------------------------------------------------------------------- #
def _wk(h, m):
    # 2026-07-10 is a Friday (a trading weekday).
    return datetime(2026, 7, 10, h, m, tzinfo=NY)


class TestAssessTiming:
    def test_weekend_is_closed(self):
        sat = datetime(2026, 7, 11, 11, 0, tzinfo=NY)
        assert assess_timing(sat, "bear_call")["entry_quality"] == "closed"
        assert assess_timing(sat, "bear_call")["market_open"] is False

    def test_pre_market_closed(self):
        assert assess_timing(_wk(9, 0), "bear_call")["window"] == "pre_market"

    def test_after_hours_closed(self):
        assert assess_timing(_wk(16, 5), "bear_call")["window"] == "after_hours"

    def test_opening_bell_avoid(self):
        t = assess_timing(_wk(9, 35), "bear_call")
        assert t["window"] == "opening_bell"
        assert t["entry_quality"] == "avoid"

    def test_morning_prime_best_for_credit_spread(self):
        t = assess_timing(_wk(10, 30), "bear_call")
        assert t["window"] == "morning_prime"
        assert t["entry_quality"] == "best"

    def test_midday_best_for_iron_condor(self):
        assert assess_timing(_wk(12, 30), "iron_condor")["entry_quality"] == "best"
        assert assess_timing(_wk(12, 30), "bear_call")["entry_quality"] == "fair"

    def test_power_hour_avoid(self):
        t = assess_timing(_wk(15, 30), "bear_call")
        assert t["window"] == "power_hour"
        assert t["entry_quality"] == "avoid"


class TestAssessTimingSession:
    def test_holiday_session_is_closed(self):
        # Weekday, midday, but the calendar says not a trading day.
        session = {"is_trading_day": False, "close_hm": 960}
        t = assess_timing(_wk(11, 0), "bear_call", session=session)
        assert t["window"] == "closed"
        assert "holiday" in t["recommendation"]

    def test_early_close_shifts_power_hour(self):
        # Half-day close at 13:00 (780 min): 12:15 should already be power_hour.
        session = {"is_trading_day": True, "close_hm": 780}
        assert assess_timing(_wk(12, 15), "bear_call", session=session)["window"] == "power_hour"
        assert assess_timing(_wk(13, 30), "bear_call", session=session)["window"] == "after_hours"


class TestEventGuidanceStatic:
    def test_ten_am_window_flagged(self):
        e = event_guidance(_wk(10, 5), "index")
        assert e["source"] == "static"
        assert e["near_release_window"] is True
        assert any("10:00" in w for w in e["warnings"])

    def test_fomc_slot_flagged(self):
        assert any("FOMC" in w for w in event_guidance(_wk(14, 5), "index")["warnings"])

    def test_quiet_time_no_warnings(self):
        e = event_guidance(_wk(11, 0), "index")
        assert e["warnings"] == []

    def test_stock_underlying_adds_earnings_check(self):
        assert any(
            "earnings" in v.lower()
            for v in event_guidance(_wk(11, 0), "stock")["verify_before_trading"]
        )
        assert not any(
            "earnings" in v.lower()
            for v in event_guidance(_wk(11, 0), "index")["verify_before_trading"]
        )


class TestEventGuidanceLive:
    def _events(self):
        return [
            {
                "event": "FOMC Statement",
                "time_et": "14:00 ET",
                "impact": "high",
                "actual": None,
                "consensus": None,
                "previous": None,
            },
            {
                "event": "Existing Home Sales",
                "time_et": "10:00 ET",
                "impact": "medium",
                "actual": None,
                "consensus": None,
                "previous": None,
            },
        ]

    def test_live_events_drive_source_and_high_impact(self):
        e = event_guidance(_wk(9, 0), "index", live_events=self._events())
        assert e["source"] == "nasdaq"
        assert e["high_impact_today"] == ["FOMC Statement"]
        assert any("FOMC Statement" in w for w in e["warnings"])
        assert e["events_today"] == self._events()

    def test_imminent_event_flagged(self):
        # now 09:45; the 10:00 event is within 30 min -> imminent.
        e = event_guidance(_wk(9, 45), "index", live_events=self._events())
        assert e["near_release_window"] is True
        assert any("Imminent" in w for w in e["warnings"])

    def test_empty_live_list_still_nasdaq_source(self):
        e = event_guidance(_wk(11, 0), "index", live_events=[])
        assert e["source"] == "nasdaq"
        assert e["warnings"] == []


# --------------------------------------------------------------------------- #
# Quote resolution / --allow-stale gating
# --------------------------------------------------------------------------- #
class TestResolveQuote:
    def _call(self, bid, ask, last, close, g_delta, g_iv, allow_stale):
        return _resolve_quote(
            bid,
            ask,
            last,
            close,
            g_delta,
            g_iv,
            spot=100,
            strike=110,
            right="C",
            T=0.02,
            r=0.045,
            allow_stale=allow_stale,
        )

    def test_live_bid_ask_used_for_mid(self):
        mid, delta, iv, stale, no_live = self._call(1.0, 1.2, None, 5.0, 0.15, 0.2, False)
        assert mid == pytest.approx(1.1)
        assert (delta, iv) == (0.15, 0.2)  # straight from IBKR greeks
        assert stale is False
        assert no_live is False

    def test_no_live_quote_default_leaves_unpriceable(self):
        # Only a close available, greeks absent, allow_stale False -> nothing usable.
        mid, delta, iv, stale, no_live = self._call(None, None, None, 5.0, None, None, False)
        assert mid is None  # close NOT used
        assert iv is None  # greeks NOT computed
        assert stale is False
        assert no_live is True

    def test_allow_stale_prices_from_close_and_derives_iv(self):
        mid, delta, iv, stale, no_live = self._call(None, None, None, 5.0, None, None, True)
        assert mid == 5.0  # yesterday's close
        assert iv is not None and iv > 0  # BS-inverted from the close
        assert stale is True
        assert no_live is True

    def test_ibkr_greeks_preferred_even_when_stale_allowed(self):
        # If IBKR provides greeks, we never overwrite them with a BS estimate.
        mid, delta, iv, stale, no_live = self._call(None, None, None, 5.0, 0.15, 0.33, True)
        assert (delta, iv) == (0.15, 0.33)


# --------------------------------------------------------------------------- #
# Underlying resolution
# --------------------------------------------------------------------------- #
class TestResolveUnderlying:
    def test_index_symbols_route_to_index_contract(self):
        for sym, exch in [("SPX", "CBOE"), ("NDX", "NASDAQ"), ("RUT", "CBOE"), ("VIX", "CBOE")]:
            contract, sec_type, asset_type = resolve_underlying(sym)
            assert sec_type == "IND"
            assert asset_type == "index"
            assert contract.exchange == exch
            assert contract.secType == "IND"

    def test_stock_symbol_routes_to_stock(self):
        contract, sec_type, asset_type = resolve_underlying("AAPL")
        assert sec_type == "STK"
        assert asset_type == "stock"
        assert contract.exchange == "SMART"

    def test_lowercase_is_normalized(self):
        contract, sec_type, asset_type = resolve_underlying("spx")
        assert asset_type == "index"
        assert contract.symbol == "SPX"


class TestResolveEntryDelta:
    def test_index_default_is_010(self):
        assert resolve_entry_delta("NDX", "index", None) == 0.10

    def test_stock_default_is_020(self):
        assert resolve_entry_delta("AAPL", "stock", None) == 0.20

    def test_explicit_overrides_class_default(self):
        assert resolve_entry_delta("NDX", "index", 0.25) == 0.25


# --------------------------------------------------------------------------- #
# Probability of profit
# --------------------------------------------------------------------------- #
class TestPopShort:
    def test_delta_is_primary(self):
        # short call delta 0.20 -> POP ~ 0.80
        pop = pop_short("C", 100, 105, delta=0.20, iv=None, T=0.001, r=0.045)
        assert pop == pytest.approx(0.80)

    def test_put_delta_uses_absolute_value(self):
        pop = pop_short("P", 100, 95, delta=-0.25, iv=None, T=0.001, r=0.045)
        assert pop == pytest.approx(0.75)

    def test_bs_fallback_when_delta_missing(self):
        # OTM call, should return a high (>0.5) POP from N(d2)
        pop = pop_short("C", 100, 110, delta=None, iv=0.20, T=0.02, r=0.045)
        assert pop is not None
        assert 0.5 < pop < 1.0

    def test_returns_none_without_usable_inputs(self):
        assert pop_short("C", 100, 105, delta=None, iv=None, T=0.001, r=0.045) is None

    def test_pop_clamped_to_unit_interval(self):
        assert 0.0 <= pop_short("C", 100, 105, delta=1.5, iv=None, T=0.001, r=0.045) <= 1.0


# --------------------------------------------------------------------------- #
# Bear call verticals
# --------------------------------------------------------------------------- #
class TestBuildVerticalsBearCall:
    def _calls(self):
        # spot 100; OTM calls above spot
        return [
            _opt(100, 1.20, delta=0.50),
            _opt(105, 0.60, delta=0.30),
            _opt(110, 0.25, delta=0.15),
            _opt(115, 0.10, delta=0.07),
        ]

    def test_produces_credit_spreads(self):
        out = build_verticals(self._calls(), "C", spot=100, budget=1000, T=0.01, r=0.045)
        assert out
        for c in out:
            assert c["strategy"] == "bear_call"
            assert c["legs"][0]["action"] == "sell"
            assert c["legs"][1]["action"] == "buy"
            # long strike is further OTM than short
            assert c["legs"][1]["strike"] > c["legs"][0]["strike"]
            assert c["net_credit"] > 0
            assert c["max_loss_per_contract"] > 0
            assert c["contracts"] >= 1

    def test_max_loss_matches_width_minus_credit(self):
        out = build_verticals(self._calls(), "C", spot=100, budget=1000, T=0.01, r=0.045)
        c = out[0]
        width = c["width"]
        expected_loss = round((width - c["net_credit"]) * 100, 2)
        assert c["max_loss_per_contract"] == pytest.approx(expected_loss, abs=0.02)

    def test_budget_caps_position_size(self):
        # tiny budget -> at most one contract, and only if a spread fits
        out = build_verticals(self._calls(), "C", spot=100, budget=200, T=0.01, r=0.045)
        for c in out:
            assert c["max_loss_total"] <= 200 + 1e-6

    def test_does_not_sell_itm_calls(self):
        out = build_verticals(self._calls(), "C", spot=100, budget=1000, T=0.01, r=0.045)
        for c in out:
            assert c["legs"][0]["strike"] >= 100

    def test_min_pop_filter(self):
        out = build_verticals(
            self._calls(), "C", spot=100, budget=1000, T=0.01, r=0.045, min_pop=0.80
        )
        for c in out:
            assert c["pop"] >= 0.80

    def test_max_width_filter(self):
        out = build_verticals(
            self._calls(), "C", spot=100, budget=1000, T=0.01, r=0.045, max_width=5
        )
        for c in out:
            assert c["width"] <= 5

    def test_max_short_delta_filter(self):
        # calls have deltas 0.50/0.30/0.15/0.07; cap at 0.20 keeps only 0.15 & 0.07 shorts
        out = build_verticals(
            self._calls(), "C", spot=100, budget=1000, T=0.01, r=0.045, max_short_delta=0.20
        )
        assert out
        for c in out:
            assert c["short_delta"] <= 0.20
            assert c["legs"][0]["strike"] in (110, 115)  # 0.30-delta 105 short excluded

    def test_reports_short_delta_and_distance(self):
        out = build_verticals(self._calls(), "C", spot=100, budget=1000, T=0.01, r=0.045)
        c = next(x for x in out if x["legs"][0]["strike"] == 110)
        assert c["short_delta"] == pytest.approx(0.15)  # from IBKR delta
        assert c["distance_to_short"] == pytest.approx(10.0)  # 110 - 100
        assert c["distance_to_short_pct"] == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# Bull put verticals
# --------------------------------------------------------------------------- #
class TestBuildVerticalsBullPut:
    def _puts(self):
        # spot 100; OTM puts below spot
        return [
            _opt(85, 0.10, delta=-0.07, right="P"),
            _opt(90, 0.25, delta=-0.15, right="P"),
            _opt(95, 0.60, delta=-0.30, right="P"),
            _opt(100, 1.20, delta=-0.50, right="P"),
        ]

    def test_produces_credit_spreads(self):
        out = build_verticals(self._puts(), "P", spot=100, budget=1000, T=0.01, r=0.045)
        assert out
        for c in out:
            assert c["strategy"] == "bull_put"
            # long put is further OTM (lower strike) than short
            assert c["legs"][1]["strike"] < c["legs"][0]["strike"]
            assert c["net_credit"] > 0

    def test_does_not_sell_otm_above_spot(self):
        out = build_verticals(self._puts(), "P", spot=100, budget=1000, T=0.01, r=0.045)
        for c in out:
            assert c["legs"][0]["strike"] <= 100

    def test_breakeven_below_short_strike(self):
        out = build_verticals(self._puts(), "P", spot=100, budget=1000, T=0.01, r=0.045)
        for c in out:
            assert c["breakeven"] < c["legs"][0]["strike"]

    def test_distance_is_spot_minus_short_strike(self):
        out = build_verticals(self._puts(), "P", spot=100, budget=1000, T=0.01, r=0.045)
        c = next(x for x in out if x["legs"][0]["strike"] == 95)
        assert c["distance_to_short"] == pytest.approx(5.0)  # 100 - 95, positive cushion
        assert c["short_delta"] == pytest.approx(0.30)


# --------------------------------------------------------------------------- #
# Iron condor
# --------------------------------------------------------------------------- #
class TestBuildIronCondors:
    def _calls(self):
        return [
            _opt(105, 0.60, delta=0.30),
            _opt(110, 0.25, delta=0.15),
            _opt(115, 0.10, delta=0.07),
        ]

    def _puts(self):
        return [
            _opt(85, 0.10, delta=-0.07, right="P"),
            _opt(90, 0.25, delta=-0.15, right="P"),
            _opt(95, 0.60, delta=-0.30, right="P"),
        ]

    def _condors(self):
        return build_iron_condors(
            self._calls(), self._puts(), spot=100, budget=1000, T=0.01, r=0.045
        )

    def test_produces_condors_with_four_legs(self):
        out = self._condors()
        assert out
        for c in out:
            assert c["strategy"] == "iron_condor"
            assert len(c["legs"]) == 4
            # short strikes bracket spot
            assert c["breakeven_low"] < 100 < c["breakeven_high"]

    def test_condor_pop_is_two_sided(self):
        for c in self._condors():
            # POP of staying inside the range is a valid probability
            assert 0.0 <= c["pop"] <= 1.0

    def test_reports_short_leg_deltas_and_distances(self):
        for c in self._condors():
            assert c["short_call_delta"] is not None
            assert c["short_put_delta"] is not None
            assert c["call_distance_to_short"] > 0  # short call above spot
            assert c["put_distance_to_short"] > 0  # short put below spot

    def test_delta_cap_applies_to_both_short_legs(self):
        out = build_iron_condors(
            self._calls(),
            self._puts(),
            spot=100,
            budget=1000,
            T=0.01,
            r=0.045,
            max_short_delta=0.20,
        )
        for c in out:
            assert c["short_call_delta"] <= 0.20
            assert c["short_put_delta"] <= 0.20

    def test_short_strikes_do_not_cross(self):
        out = self._condors()
        for c in out:
            short_put = c["legs"][0]["strike"]
            short_call = c["legs"][2]["strike"]
            assert short_put < short_call


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
class TestRankCandidates:
    def test_ranks_by_ev_then_pop(self):
        cands = [
            {"ev_total": 10, "pop": 0.7},
            {"ev_total": 50, "pop": 0.6},
            {"ev_total": 50, "pop": 0.9},
        ]
        ranked = rank_candidates(cands, top=3)
        assert ranked[0] == {"ev_total": 50, "pop": 0.9}  # higher EV, POP tiebreak
        assert ranked[1] == {"ev_total": 50, "pop": 0.6}
        assert ranked[2] == {"ev_total": 10, "pop": 0.7}

    def test_top_limits_length(self):
        cands = [{"ev_total": i, "pop": 0.5} for i in range(10)]
        assert len(rank_candidates(cands, top=3)) == 3

    def test_empty_input(self):
        assert rank_candidates([], top=5) == []


# --------------------------------------------------------------------------- #
# Validation / edge cases (offline)
# --------------------------------------------------------------------------- #
class TestValidation:
    def test_unknown_spread_type_errors(self):
        result = asyncio.run(find_0dte_spreads("SPX", spread_type="butterfly"))
        assert result["success"] is False
        assert "Unknown spread type" in result["error"]

    def test_crossed_quotes_rejected(self):
        # long mid exceeds short mid -> no credit -> no candidates
        calls = [_opt(105, 0.20, delta=0.30), _opt(110, 0.60, delta=0.15)]
        out = build_verticals(calls, "C", spot=100, budget=1000, T=0.01, r=0.045)
        assert out == []

    def test_budget_too_small_yields_nothing(self):
        calls = [_opt(105, 0.60, delta=0.30), _opt(115, 0.10, delta=0.07)]
        # width 10 -> max loss ~ (10 - 0.5)*100 = 950 per contract; budget 100 fits none
        out = build_verticals(calls, "C", spot=100, budget=100, T=0.01, r=0.045)
        assert out == []


# --------------------------------------------------------------------------- #
# Execute guardrails (offline — guards return before any IB call)
# --------------------------------------------------------------------------- #
class TestExecuteGuards:
    def _cand(self, max_loss_total=500.0):
        return {"max_loss_total": max_loss_total, "net_credit": 0.85, "contracts": 5, "legs": []}

    def _run(self, ranked, pick, account, budget):
        # ib=None is safe: every case here fails a guard before _place_spread_order.
        return asyncio.run(
            _maybe_execute(
                None,
                ranked,
                pick,
                account,
                budget,
                None,
                "SPX",
                "20260710",
                "SMART",
                "SPXW",
                "bear_call",
                spot=100,
                T=0.01,
                rate=0.045,
                underlying_conid=1,
                underlying_exch="SMART",
                stop_cfg={"mult": 2.0, "buffer": 0, "delta": None, "fill_timeout": 1},
            )
        )

    def test_no_candidates(self):
        res = self._run([], 1, "U123", 1000)
        assert res["ok"] is False
        assert "No candidates" in res["error"]

    def test_pick_out_of_range(self):
        res = self._run([self._cand()], 3, "U123", 1000)
        assert res["ok"] is False
        assert "out of range" in res["error"]

    def test_account_required(self):
        res = self._run([self._cand()], 1, None, 1000)
        assert res["ok"] is False
        assert "Account required" in res["error"]

    def test_budget_reexceeded_blocks(self):
        res = self._run([self._cand(max_loss_total=5000.0)], 1, "U123", 1000)
        assert res["ok"] is False
        assert "exceeds budget" in res["error"]


# --------------------------------------------------------------------------- #
# Duplicate-order guard (offline, with a fake IB)
# --------------------------------------------------------------------------- #
class _FakeOrder:
    def __init__(self, order_id, ref, account):
        self.orderId = order_id
        self.orderRef = ref
        self.account = account


class _FakeStatus:
    def __init__(self, status):
        self.status = status


class _FakeTrade:
    def __init__(self, order_id, ref, account, status):
        self.order = _FakeOrder(order_id, ref, account)
        self.orderStatus = _FakeStatus(status)


class _FakeIB:
    def __init__(self, trades):
        self._trades = trades
        self.cancelled = []

    async def reqAllOpenOrdersAsync(self):
        return self._trades

    def openTrades(self):
        return self._trades

    def cancelOrder(self, order):
        self.cancelled.append(order.orderId)

    async def qualifyContractsAsync(self, *contracts):
        return []  # forces _place_spread_order to bail after the guard/replace


class TestDuplicateGuard:
    REF = "ZDTE_bear_call_SPX_20260710"

    def _cand(self):
        return {
            "max_loss_total": 500.0,
            "net_credit": 0.85,
            "contracts": 5,
            "legs": [{"action": "sell", "strike": 100, "right": "C"}],
        }

    def _run(self, ib, replace):
        return asyncio.run(
            _maybe_execute(
                ib,
                [self._cand()],
                1,
                "U123",
                1000,
                None,
                "SPX",
                "20260710",
                "SMART",
                "SPXW",
                "bear_call",
                replace=replace,
                spot=100,
                T=0.01,
                rate=0.045,
                underlying_conid=1,
                underlying_exch="SMART",
                stop_cfg={"mult": 2.0, "buffer": 0, "delta": None, "fill_timeout": 1},
            )
        )

    def test_active_duplicate_is_refused(self):
        ib = _FakeIB([_FakeTrade(42, self.REF, "U123", "PreSubmitted")])
        res = self._run(ib, replace=False)
        assert res["ok"] is False
        assert "Duplicate" in res["error"]
        assert res["existing_order_id"] == 42
        assert ib.cancelled == []  # nothing cancelled when refusing

    def test_replace_cancels_existing(self):
        ib = _FakeIB([_FakeTrade(42, self.REF, "U123", "PreSubmitted")])
        self._run(ib, replace=True)
        assert ib.cancelled == [42]  # existing order was cancelled before re-placing

    def test_inactive_order_is_not_a_duplicate(self):
        # A cancelled/filled order with the same ref must not block a new placement.
        ib = _FakeIB([_FakeTrade(42, self.REF, "U123", "Cancelled")])
        res = self._run(ib, replace=False)
        assert res["ok"] is False  # bails at qualify, NOT at the duplicate guard
        assert "Duplicate" not in (res.get("error") or "")

    def test_different_account_is_not_a_duplicate(self):
        ib = _FakeIB([_FakeTrade(42, self.REF, "U999", "PreSubmitted")])
        res = self._run(ib, replace=False)
        assert "Duplicate" not in (res.get("error") or "")


# --------------------------------------------------------------------------- #
# Live IB integration (manual — requires TWS/Gateway on 7496)
# --------------------------------------------------------------------------- #
@pytest.mark.manual
class TestLiveIB:
    def test_spx_expiries(self):
        result = asyncio.run(get_0dte_expiries("SPX"))
        assert result["success"] is True
        assert result["asset_type"] == "index"
        assert isinstance(result["expiries"], list)

    def test_spx_bear_call(self):
        result = asyncio.run(find_0dte_spreads("SPX", spread_type="bear_call", budget=2000))
        assert result["success"] is True
        assert result["asset_type"] == "index"
        assert "account" in result
        assert result["dry_run"] is True  # no --execute → nothing placed
        if result["candidates"]:
            c = result["best"]
            assert c["max_loss_total"] <= 2000 + 1e-6

    def test_invalid_account_rejected(self):
        result = asyncio.run(find_0dte_spreads("SPX", spread_type="bear_call", account="U0000000"))
        assert result["success"] is False
        assert "not found" in result["error"]

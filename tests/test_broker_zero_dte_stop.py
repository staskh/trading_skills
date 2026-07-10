# ABOUTME: Tests for 0DTE stop-loss level math (pure); order placement is manual/live.
# ABOUTME: Verifies trigger direction, level combination, and the premium-cap solve.

from trading_skills.broker.zero_dte_stop import (
    reconstruct_spread,
    resolve_stop_cfg,
    stop_plan,
    vertical_stop_level,
)


class TestVerticalStopLevel:
    def test_bear_call_triggers_above_spot(self):
        # spot 100, short 105 / long 110 call, credit 0.60
        plan = vertical_stop_level(
            "C",
            105,
            110,
            0.60,
            100,
            T=0.01,
            r=0.045,
            sigma=0.20,
            mult=2.0,
            buffer_pts=0.0,
            target_delta=None,
        )
        assert plan["is_more"] is True  # bear call: danger is up
        assert plan["trigger"] > 100  # trigger above spot
        assert plan["trigger"] <= 105  # not beyond the short strike

    def test_bull_put_triggers_below_spot(self):
        plan = vertical_stop_level(
            "P",
            95,
            90,
            0.60,
            100,
            T=0.01,
            r=0.045,
            sigma=0.20,
            mult=2.0,
            buffer_pts=0.0,
            target_delta=None,
        )
        assert plan["is_more"] is False  # bull put: danger is down
        assert plan["trigger"] < 100
        assert plan["trigger"] >= 95

    def test_buffer_tightens_bear_call_below_strike(self):
        base = vertical_stop_level(
            "C",
            105,
            110,
            0.60,
            100,
            T=0.01,
            r=0.045,
            sigma=0.20,
            mult=0,
            buffer_pts=0.0,
            target_delta=None,
        )
        buffered = vertical_stop_level(
            "C",
            105,
            110,
            0.60,
            100,
            T=0.01,
            r=0.045,
            sigma=0.20,
            mult=0,
            buffer_pts=3.0,
            target_delta=None,
        )
        assert base["trigger"] == 105  # at the short strike
        assert buffered["trigger"] == 102  # 3 pts earlier

    def test_premium_cap_can_bind_before_the_strike(self):
        # A cheap far-OTM spread: value doubles well before the strike is reached.
        plan = vertical_stop_level(
            "C",
            105,
            110,
            0.20,
            100,
            T=0.01,
            r=0.045,
            sigma=0.20,
            mult=2.0,
            buffer_pts=0.0,
            target_delta=None,
        )
        # premium level should be at/below the strike level and be the binding one
        assert plan["levels"]["premium"] is not None
        assert plan["trigger"] <= plan["levels"]["strike"]

    def test_premium_cap_disabled_when_target_exceeds_width(self):
        # width 5, credit 3, mult 2 -> target 6 > width -> no premium level, strike governs
        plan = vertical_stop_level(
            "C",
            105,
            110,
            3.0,
            100,
            T=0.01,
            r=0.045,
            sigma=0.20,
            mult=2.0,
            buffer_pts=0.0,
            target_delta=None,
        )
        assert plan["levels"]["premium"] is None
        assert plan["binding"] == "strike"


class TestStopPlan:
    def _bear_call(self):
        return {
            "strategy": "bear_call",
            "width": 5,
            "net_credit": 0.60,
            "contracts": 3,
            "legs": [
                {"action": "sell", "right": "C", "strike": 105, "iv": 20.0},
                {"action": "buy", "right": "C", "strike": 110, "iv": 19.0},
            ],
        }

    def _iron_condor(self):
        return {
            "strategy": "iron_condor",
            "call_width": 5,
            "put_width": 5,
            "net_credit": 1.2,
            "contracts": 2,
            "legs": [
                {"action": "sell", "right": "P", "strike": 95, "iv": 21.0},
                {"action": "buy", "right": "P", "strike": 90, "iv": 22.0},
                {"action": "sell", "right": "C", "strike": 105, "iv": 20.0},
                {"action": "buy", "right": "C", "strike": 110, "iv": 19.0},
            ],
        }

    def test_vertical_returns_single_side(self):
        plans = stop_plan(
            self._bear_call(), 100, 0.01, 0.045, mult=2.0, buffer_pts=0, target_delta=None
        )
        assert len(plans) == 1
        assert plans[0]["side"] == "C"
        assert plans[0]["is_more"] is True

    def test_condor_returns_two_bracketing_sides(self):
        plans = stop_plan(
            self._iron_condor(), 100, 0.01, 0.045, mult=2.0, buffer_pts=0, target_delta=None
        )
        assert {p["side"] for p in plans} == {"call", "put"}
        call = next(p for p in plans if p["side"] == "call")
        put = next(p for p in plans if p["side"] == "put")
        assert call["is_more"] is True and call["trigger"] > 100
        assert put["is_more"] is False and put["trigger"] < 100


class TestResolveStopCfg:
    def test_preset_applied_when_args_none(self):
        cfg = resolve_stop_cfg("NDX", None, None, None, 20.0)
        assert cfg["mult"] == 3.0  # NDX preset
        assert cfg["delta"] == 0.35
        assert cfg["preset_symbol"] == "NDX"

    def test_explicit_args_override_preset(self):
        cfg = resolve_stop_cfg("NDX", 1.5, 10.0, None, 20.0)
        assert cfg["mult"] == 1.5  # explicit wins
        assert cfg["buffer"] == 10.0
        assert cfg["delta"] == 0.35  # still from preset

    def test_unlisted_symbol_uses_default(self):
        cfg = resolve_stop_cfg("AAPL", None, None, None, 20.0)
        assert cfg["mult"] == 2.0
        assert cfg["delta"] is None
        assert cfg["preset_symbol"] == "_default"


class TestReconstructSpread:
    def test_bear_call_from_positions(self):
        legs = [
            {"right": "C", "strike": 105, "qty": -1, "conId": 1},  # short lower
            {"right": "C", "strike": 110, "qty": 1, "conId": 2},  # long higher
        ]
        cand = reconstruct_spread(legs)
        assert cand["strategy"] == "bear_call"
        assert cand["legs"][0] == {"action": "sell", "right": "C", "strike": 105}
        assert cand["width"] == 5
        assert cand["contracts"] == 1
        assert cand["_close_conids"] == [(1, "BUY"), (2, "SELL")]

    def test_bull_put_from_positions(self):
        legs = [
            {"right": "P", "strike": 90, "qty": 1, "conId": 3},  # long lower
            {"right": "P", "strike": 95, "qty": -1, "conId": 4},  # short higher
        ]
        cand = reconstruct_spread(legs)
        assert cand["strategy"] == "bull_put"
        assert cand["legs"][0]["strike"] == 95  # short first
        assert cand["_close_conids"][0] == (4, "BUY")  # short → buy to close

    def test_iron_condor_from_positions(self):
        legs = [
            {"right": "P", "strike": 90, "qty": 1, "conId": 1},
            {"right": "P", "strike": 95, "qty": -1, "conId": 2},
            {"right": "C", "strike": 105, "qty": -1, "conId": 3},
            {"right": "C", "strike": 110, "qty": 1, "conId": 4},
        ]
        cand = reconstruct_spread(legs)
        assert cand["strategy"] == "iron_condor"
        assert cand["call_width"] == 5 and cand["put_width"] == 5
        assert len(cand["_close_conids"]) == 4

    def test_unrecognized_returns_none(self):
        assert reconstruct_spread([{"right": "C", "strike": 105, "qty": -1, "conId": 1}]) is None

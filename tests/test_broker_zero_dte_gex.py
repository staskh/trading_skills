# ABOUTME: Tests for the 0DTE gamma-exposure (GEX) profile.
# ABOUTME: Pure functions — no IB connection needed.

from datetime import datetime

from trading_skills.black_scholes import black_scholes_gamma
from trading_skills.broker.zero_dte import NY, assess_timing, build_timing
from trading_skills.broker.zero_dte_gex import (
    CONTRACT_MULTIPLIER,
    NEUTRAL_BAND,
    annotate_candidate,
    apply_gex_gate,
    build_gex_profile,
    find_flip_level,
    gex_guidance,
    resolve_weight_source,
    strike_gex,
)

SPOT = 5000.0
T = 4 / (365 * 24)  # ~4 hours to expiry
RATE = 0.045

# A 0DTE with ~4h left and 15% IV has a ~0.3% daily sigma, so gamma is only material
# within a fraction of a percent of spot. Profile tests therefore state gamma directly
# (it is an input from IBKR's model greeks); only the flip scan, which re-derives gamma
# across spot levels, needs Black-Scholes and realistic near-spot strikes.
TYPICAL_GAMMA = 0.001

_MORNING = datetime(2026, 7, 10, 10, 30, tzinfo=NY)  # Friday, morning_prime
_WEEKEND = datetime(2026, 7, 11, 11, 0, tzinfo=NY)  # Saturday


async def _no_sleep(_seconds):
    """Skip the OI settle-wait in tests."""


def _leg(strike, right, *, volume=0, oi=None, iv=0.15, gamma=TYPICAL_GAMMA):
    """A quoted chain leg as the fetch layer produces it."""
    return {
        "strike": float(strike),
        "right": right,
        "gamma": gamma,
        "iv": iv,
        "volume": volume,
        "open_interest": oi,
    }


def _bs_leg(strike, right, *, volume=0, iv=0.15):
    """A leg whose gamma is the true Black-Scholes gamma at SPOT (for flip tests)."""
    return _leg(
        strike, right, volume=volume, iv=iv, gamma=black_scholes_gamma(SPOT, strike, T, RATE, iv)
    )


class TestStrikeGex:
    def test_dollar_gamma_per_one_percent(self):
        # 0.01 gamma x 100 contracts x 100 multiplier = $100 of delta per 1 point;
        # a 1% move at spot 5000 is 50 points -> but GEX quotes $delta per 1% move:
        # 0.01 * 100 * 100 * 5000^2 * 0.01 = $25,000,000.
        assert strike_gex(0.01, 100, 5000.0) == 25_000_000.0

    def test_scales_with_size(self):
        one = strike_gex(0.002, 50, SPOT)
        assert strike_gex(0.002, 100, SPOT) == 2 * one

    def test_multiplier_applied(self):
        assert strike_gex(0.001, 10, SPOT) == 0.001 * 10 * CONTRACT_MULTIPLIER * SPOT**2 * 0.01


class TestWeightSource:
    def test_auto_prefers_volume_when_it_printed(self):
        legs = [_leg(5000, "C", volume=1200, oi=800)]
        assert resolve_weight_source(legs, "auto") == "volume"

    def test_auto_falls_back_to_oi_before_any_prints(self):
        legs = [_leg(5000, "C", volume=0, oi=800)]
        assert resolve_weight_source(legs, "auto") == "oi"

    def test_explicit_choice_wins(self):
        legs = [_leg(5000, "C", volume=1200, oi=800)]
        assert resolve_weight_source(legs, "oi") == "oi"


class TestBuildGexProfile:
    def test_call_heavy_book_is_positive_gamma(self):
        calls = [_leg(k, "C", volume=5000) for k in (5050, 5100, 5150)]
        puts = [_leg(k, "P", volume=50) for k in (4850, 4900, 4950)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["available"]
        assert p["net_gex"] > NEUTRAL_BAND
        assert p["regime"] == "positive_gamma"

    def test_put_heavy_book_is_negative_gamma(self):
        calls = [_leg(k, "C", volume=50) for k in (5050, 5100)]
        puts = [_leg(k, "P", volume=8000) for k in (4900, 4950)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["net_gex"] < -NEUTRAL_BAND
        assert p["regime"] == "negative_gamma"

    def test_balanced_book_is_neutral(self):
        calls = [_leg(5050, "C", volume=10)]
        puts = [_leg(4950, "P", volume=10)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["regime"] == "neutral_gamma"

    def test_walls_are_the_heaviest_gamma_strikes_each_side(self):
        calls = [
            _leg(5050, "C", volume=100),
            _leg(5100, "C", volume=9000),  # call wall
            _leg(5200, "C", volume=200),
        ]
        puts = [
            _leg(4800, "P", volume=300),
            _leg(4900, "P", volume=7000),  # put wall
            _leg(4950, "P", volume=100),
        ]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["call_wall"] == 5100.0
        assert p["put_wall"] == 4900.0

    def test_walls_stay_on_their_side_of_spot(self):
        # The heaviest call strike is BELOW spot; it must not become the call wall.
        calls = [_leg(4900, "C", volume=9000), _leg(5100, "C", volume=500)]
        puts = [_leg(4950, "P", volume=500)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["call_wall"] == 5100.0

    def test_legs_without_gamma_or_size_are_counted_not_used(self):
        calls = [
            _leg(5100, "C", volume=1000),
            _leg(5150, "C", volume=0),  # no size -> unusable
            # No gamma AND no IV -> nothing to derive from.
            {"strike": 5200.0, "right": "C", "gamma": None, "iv": None, "volume": 900},
        ]
        puts = [_leg(4900, "P", volume=1000)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["coverage"]["missing_gamma"] == 1
        assert p["coverage"]["missing_weight"] == 1
        assert p["coverage"]["strikes"] == 2  # 5100 and 4900

    def test_missing_gamma_is_derived_from_iv(self):
        # Off-hours IBKR streams no model gamma, but the leg still carries an IV —
        # Black-Scholes recovers it rather than dropping the strike.
        calls = [{"strike": 5005.0, "right": "C", "gamma": None, "iv": 0.15, "volume": 1000}]
        puts = [_leg(4900, "P", volume=1000)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["coverage"]["derived_gamma"] == 1
        assert p["coverage"]["missing_gamma"] == 0
        assert any("Black-Scholes" in c for c in p["caveats"])

    def test_unavailable_without_gamma_anywhere(self):
        calls = [{"strike": 5100.0, "right": "C", "gamma": None, "iv": None, "volume": 100}]
        p = build_gex_profile(calls, [], SPOT, T=T, rate=RATE)
        assert p["available"] is False
        assert "reason" in p

    def test_empty_chain_unavailable(self):
        assert build_gex_profile([], [], SPOT, T=T)["available"] is False

    def test_volume_weighting_is_flagged_as_a_caveat(self):
        p = build_gex_profile(
            [_leg(5100, "C", volume=100)], [_leg(4900, "P", volume=100)], SPOT, T=T, rate=RATE
        )
        assert p["weight_source"] == "volume"
        assert any("VOLUME" in c for c in p["caveats"])

    def test_oi_weighting_flags_prior_settlement(self):
        calls = [_leg(5100, "C", volume=0, oi=1000)]
        puts = [_leg(4900, "P", volume=0, oi=1000)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["weight_source"] == "oi"
        assert any("PRIOR" in c for c in p["caveats"])


class TestFlipLevel:
    def test_flip_sits_between_the_put_and_call_concentrations(self):
        # Puts dominate below, calls above -> net GEX crosses zero between them.
        calls = [_bs_leg(5010, "C", volume=4000)]
        puts = [_bs_leg(4990, "P", volume=4000)]
        weights = {("C", 5010.0): 4000.0, ("P", 4990.0): 4000.0}
        flip = find_flip_level(calls, puts, weights, SPOT, T, RATE)
        assert flip is not None
        assert 4990 < flip < 5010

    def test_no_flip_in_a_one_sided_book(self):
        calls = [_bs_leg(5010, "C", volume=5000), _bs_leg(5020, "C", volume=5000)]
        weights = {("C", 5010.0): 5000.0, ("C", 5020.0): 5000.0}
        assert find_flip_level(calls, [], weights, SPOT, T, RATE) is None

    def test_no_flip_without_time_to_expiry(self):
        calls = [_bs_leg(5010, "C", volume=100)]
        weights = {("C", 5010.0): 100.0}
        assert find_flip_level(calls, [], weights, SPOT, None, RATE) is None

    def test_profile_reports_the_flip(self):
        calls = [_bs_leg(5010, "C", volume=4000)]
        puts = [_bs_leg(4990, "P", volume=4000)]
        p = build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)
        assert p["flip_level"] is not None
        assert 4990 < p["flip_level"] < 5010


class TestGuidance:
    def _positive(self):
        calls = [_leg(5100, "C", volume=9000)]
        puts = [_leg(4900, "P", volume=100)]
        return build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)

    def _negative(self):
        calls = [_leg(5100, "C", volume=100)]
        puts = [_leg(4900, "P", volume=9000)]
        return build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)

    def test_positive_regime_has_no_warning(self):
        g = gex_guidance(self._positive(), "bear_call", SPOT)
        assert g["regime"] == "positive_gamma"
        assert g["warnings"] == []

    def test_negative_regime_warns(self):
        g = gex_guidance(self._negative(), "bear_call", SPOT)
        assert g["regime"] == "negative_gamma"
        assert any("AMPLIFIES" in w for w in g["warnings"])

    def test_bear_call_guidance_points_at_the_call_wall(self):
        g = gex_guidance(self._positive(), "bear_call", SPOT)
        assert any("call wall" in s for s in g["strike_guidance"])

    def test_condor_gets_both_walls(self):
        g = gex_guidance(self._positive(), "iron_condor", SPOT)
        assert len(g["strike_guidance"]) == 2

    def test_unavailable_profile_yields_unavailable_guidance(self):
        g = gex_guidance({"available": False, "reason": "nope"}, "bear_call", SPOT)
        assert g["available"] is False


def _guide(calls, puts, spread_type="bear_call"):
    """Guidance for a chain, the way find_0dte_spreads assembles it."""
    return gex_guidance(build_gex_profile(calls, puts, SPOT, T=T, rate=RATE), spread_type, SPOT)


_PUT_HEAVY = ([_leg(5100, "C", volume=100)], [_leg(4900, "P", volume=9000)])
_CALL_HEAVY = ([_leg(5100, "C", volume=9000)], [_leg(4900, "P", volume=100)])


class TestGate:
    def _timing(self):
        return build_timing(_MORNING, "bear_call", "index", None, None)

    def test_negative_gamma_downgrades_the_window(self):
        assert self._timing()["entry_quality"] == "best"  # mid-morning, clock alone
        gated = apply_gex_gate(self._timing(), _guide(*_PUT_HEAVY))
        assert gated["entry_quality"] == "fair"
        assert gated["gex_gate"]["entry_quality_before"] == "best"

    def test_positive_gamma_leaves_the_window_alone(self):
        gated = apply_gex_gate(self._timing(), _guide(*_CALL_HEAVY))
        assert gated["entry_quality"] == "best"
        assert "gex_gate" not in gated

    def test_gate_never_upgrades_a_closed_market(self):
        closed = assess_timing(_WEEKEND, "bear_call")
        assert apply_gex_gate(closed, _guide(*_PUT_HEAVY))["entry_quality"] == "closed"


class TestFetchOpenInterest:
    """OI comes only from a STREAMING generic-tick-101 request, in cancelled batches."""

    class _FakeContract:
        def __init__(self, con_id, right):
            self.conId = con_id
            self.right = right

    class _FakeTicker:
        def __init__(self, contract, call_oi=float("nan"), put_oi=float("nan")):
            self.contract = contract
            self.callOpenInterest = call_oi
            self.putOpenInterest = put_oi

    class _FakeIB:
        def __init__(self, oi_map):
            self.oi_map = oi_map
            self.live = 0
            self.peak = 0
            self.cancelled = []
            self.generic_ticks = []

        def reqMktData(self, contract, genericTickList="", snapshot=False):
            self.generic_ticks.append(genericTickList)
            self.live += 1
            self.peak = max(self.peak, self.live)
            oi = self.oi_map.get(contract.conId, float("nan"))
            if contract.right == "C":
                return TestFetchOpenInterest._FakeTicker(contract, call_oi=oi)
            return TestFetchOpenInterest._FakeTicker(contract, put_oi=oi)

        def cancelMktData(self, contract):
            self.live -= 1
            self.cancelled.append(contract.conId)

    def _run(self, ib, contracts):
        import asyncio

        from trading_skills.broker.zero_dte import _fetch_open_interest

        return asyncio.run(_fetch_open_interest(ib, contracts))

    def test_reads_the_right_side_and_skips_nan(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        contracts = [self._FakeContract(1, "C"), self._FakeContract(2, "P")]
        contracts.append(self._FakeContract(3, "C"))  # no OI -> nan -> omitted
        ib = self._FakeIB({1: 4200, 2: 3100})
        assert self._run(ib, contracts) == {1: 4200, 2: 3100}

    def test_requests_generic_tick_101(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        ib = self._FakeIB({1: 10})
        self._run(ib, [self._FakeContract(1, "C")])
        assert ib.generic_ticks == ["101"]

    def test_batches_and_cancels_every_line(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        contracts = [self._FakeContract(i, "C") for i in range(50)]
        ib = self._FakeIB({i: 100 for i in range(50)})
        self._run(ib, contracts)
        assert ib.peak <= 20  # never holds more than a batch of market-data lines
        assert ib.live == 0  # everything released
        assert sorted(ib.cancelled) == list(range(50))


class TestAnnotateCandidate:
    def _profile(self):
        calls = [_leg(5100, "C", volume=9000), _leg(5150, "C", volume=100)]
        puts = [_leg(4900, "P", volume=7000)]
        return build_gex_profile(calls, puts, SPOT, T=T, rate=RATE)

    def _bear_call(self, short_strike):
        return {
            "legs": [
                {"action": "sell", "right": "C", "strike": float(short_strike)},
                {"action": "buy", "right": "C", "strike": float(short_strike) + 25},
            ]
        }

    def test_short_beyond_the_wall_is_ok(self):
        c = annotate_candidate(self._bear_call(5150), self._profile(), "bear_call")
        assert c["gex"]["call"]["placement"] == "beyond_wall"
        assert c["gex_ok"] is True

    def test_short_inside_the_wall_is_flagged(self):
        c = annotate_candidate(self._bear_call(5050), self._profile(), "bear_call")
        assert c["gex"]["call"]["placement"] == "inside_wall"
        assert c["gex_ok"] is False
        assert c["gex"]["call"]["distance_to_wall"] == 50.0

    def test_short_at_the_wall(self):
        c = annotate_candidate(self._bear_call(5100), self._profile(), "bear_call")
        assert c["gex"]["call"]["placement"] == "at_wall"
        assert c["gex_ok"] is True

    def test_bull_put_below_the_put_wall_is_ok(self):
        cand = {
            "legs": [
                {"action": "sell", "right": "P", "strike": 4850.0},
                {"action": "buy", "right": "P", "strike": 4825.0},
            ]
        }
        c = annotate_candidate(cand, self._profile(), "bull_put")
        assert c["gex"]["put"]["placement"] == "beyond_wall"

    def test_condor_needs_both_sides_ok(self):
        cand = {
            "legs": [
                {"action": "sell", "right": "C", "strike": 5150.0},  # beyond call wall
                {"action": "buy", "right": "C", "strike": 5175.0},
                {"action": "sell", "right": "P", "strike": 4950.0},  # inside put wall
                {"action": "buy", "right": "P", "strike": 4925.0},
            ]
        }
        c = annotate_candidate(cand, self._profile(), "iron_condor")
        assert c["gex"]["call"]["placement"] == "beyond_wall"
        assert c["gex"]["put"]["placement"] == "inside_wall"
        assert c["gex_ok"] is False

    def test_unavailable_profile_leaves_the_candidate_untouched(self):
        cand = self._bear_call(5100)
        out = annotate_candidate(cand, {"available": False}, "bear_call")
        assert "gex" not in out

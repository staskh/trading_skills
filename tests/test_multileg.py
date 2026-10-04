# ABOUTME: Tests for the multi-leg options strategy engine using a synthetic BS chain.
# ABOUTME: Covers regime classification, selection, builders, validation and exit plans.

from pathlib import Path

import numpy as np
import pytest
import yaml

from trading_skills.black_scholes import black_scholes_delta, black_scholes_price
from trading_skills.multileg import (
    BUILDERS,
    Chain,
    Leg,
    Opt,
    analyze,
    build_strategy,
    classify_regime,
    exit_plan,
    gate,
    pl_at_expiry,
    select_strategies,
    size_position,
)

CONFIG = (
    Path(__file__).parent.parent
    / ".claude/skills/ib-multileg-options/references/multileg_options_config.yaml"
)


@pytest.fixture(scope="module")
def cfg():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def make_chain(spot=5000.0, dte=14, step=5, base_iv=0.16, skew=0.6, r=0.04, spread=0.02):
    """Synthetic chain with put skew; bid/ask = mid -/+ spread fraction (min 0.05)."""
    t = dte / 365
    opts = []
    for k in np.arange(spot * 0.8, spot * 1.2 + step, step):
        k = float(k)
        iv = max(0.06, base_iv - skew * base_iv * np.log(k / spot))
        for right, kind in (("C", "call"), ("P", "put")):
            mid = black_scholes_price(spot, k, t, r, iv, kind)
            if mid < 0.05:
                continue
            half = max(0.05, mid * spread / 2)
            opts.append(
                Opt(
                    strike=k,
                    right=right,
                    bid=round(max(0.01, mid - half), 2),
                    ask=round(mid + half, 2),
                    delta=black_scholes_delta(spot, k, t, r, iv, kind),
                    iv=iv,
                )
            )
    return Chain(opts, spot, t, r)


def trend(n=120, start=100.0, step=0.5):
    closes = [start + i * step for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    return closes, highs, lows


class TestRegime:
    def test_uptrend_is_bull(self, cfg):
        c, h, lo = trend(step=0.8)
        r = classify_regime(c, h, lo, [0.2] * 250, cfg)
        assert r["direction"] == "BULL"

    def test_downtrend_is_bear(self, cfg):
        c, h, lo = trend(step=-0.3, start=200)
        r = classify_regime(c, h, lo, [0.2] * 250, cfg)
        assert r["direction"] == "BEAR"

    def test_flat_is_neutral(self, cfg):
        c = [100.0] * 120
        r = classify_regime(c, [101] * 120, [99] * 120, [0.2] * 250, cfg)
        assert r["direction"] == "NEUTRAL"

    def test_iv_rank_and_trend(self, cfg):
        ivs = list(np.linspace(0.10, 0.30, 250)) + [0.33]
        r = classify_regime([100.0] * 120, [101] * 120, [99] * 120, ivs, cfg)
        assert r["iv_level"] == "HIGH"
        assert r["iv_rank"] == 100.0
        assert r["iv_trend"] == "EXPANDING"

    def test_low_iv_contracting(self, cfg):
        ivs = list(np.linspace(0.30, 0.12, 250)) + [0.11]
        r = classify_regime([100.0] * 120, [101] * 120, [99] * 120, ivs, cfg)
        assert r["iv_level"] == "LOW"
        assert r["iv_trend"] == "CONTRACTING"

    def test_put_skew_not_call_rich(self, cfg):
        r = classify_regime([100.0] * 120, [101] * 120, [99] * 120, [0.2] * 10, cfg, make_chain())
        assert r["call_rich"] is False


class TestSelection:
    def base(self, **kw):
        r = {"direction": "NEUTRAL", "iv_level": "HIGH", "iv_trend": "FLAT"}
        r.update({"call_rich": False, "earnings": False})
        r.update(kw)
        return r

    def test_neutral_high(self):
        assert select_strategies(self.base())[0] == "iron_duck"

    def test_bear_mid(self):
        names = select_strategies(self.base(direction="BEAR", iv_level="MID"))
        assert names == ["bear_fly", "small_beak", "time_fly"]

    def test_earnings_only_iron_duck(self):
        assert select_strategies(self.base(earnings=True)) == ["iron_duck"]

    def test_call_rich_adds_reverse_duck(self):
        assert select_strategies(self.base(call_rich=True))[0] == "reverse_iron_duck"

    def test_butterflies_gated_when_iv_contracting(self):
        reg = self.base(iv_trend="CONTRACTING")
        assert gate("dn_fly", reg) is not None
        assert gate("iron_duck", reg) is None

    def test_time_fly_needs_expanding(self):
        assert gate("time_fly", self.base(iv_trend="FLAT")) is not None
        assert gate("time_fly", self.base(iv_trend="EXPANDING")) is None


class TestPayoff:
    def test_long_call_spread_payoff(self):
        lc = Opt(100, "C", 4.9, 5.1, 0.5, 0.2)
        sc = Opt(110, "C", 1.9, 2.1, 0.25, 0.2)
        legs = [Leg(1, lc), Leg(-1, sc)]
        assert pl_at_expiry(legs, 90) == pytest.approx(-3.0)
        assert pl_at_expiry(legs, 120) == pytest.approx(7.0)


class TestBuilders:
    @pytest.mark.parametrize("name", sorted(BUILDERS))
    def test_every_builder_produces_legs(self, cfg, name):
        out = build_strategy(name, make_chain(), cfg, is_equity=False)
        assert "legs" in out, out
        assert out["analysis"]["max_loss"] >= 0

    def test_iron_duck_structure_and_checks(self, cfg):
        out = build_strategy("iron_duck", make_chain(base_iv=0.22), cfg, is_equity=False)
        legs = out["legs"]
        qtys = [(lg.qty, lg.opt.right) for lg in legs]
        assert qtys == [(-1, "C"), (1, "C"), (-1, "P"), (1, "P")]
        assert abs(legs[0].opt.delta) == pytest.approx(0.65, abs=0.08)
        assert legs[1].opt.strike > legs[0].opt.strike
        assert set(out["checks"]) >= {"pop_ok", "no_upside_risk", "loss_at_be_le_credit"}
        if out["passed"]:
            assert out["analysis"]["upside_pl_at_expiry"] >= -0.01
            assert out["analysis"]["pop"] >= 0.85

    def test_checks_are_plain_bools(self, cfg):
        for name in BUILDERS:
            out = build_strategy(name, make_chain(), cfg, is_equity=False)
            assert all(type(v) is bool for v in out.get("checks", {}).values()), name

    def test_dn_fly_equal_wings(self, cfg):
        out = build_strategy("dn_fly", make_chain(), cfg)
        k = [lg.opt.strike for lg in out["legs"]]
        assert k[1] - k[0] == pytest.approx(k[2] - k[1], abs=5)
        assert out["analysis"]["price_type"] == "debit"

    def test_bear_fly_uses_puts_around_30_delta(self, cfg):
        out = build_strategy("bear_fly", make_chain(), cfg)
        body = [lg for lg in out["legs"] if lg.qty == -2][0]
        assert body.opt.right == "P"
        assert abs(body.opt.delta) == pytest.approx(0.30, abs=0.05)

    def test_big_beak_deltas(self, cfg):
        out = build_strategy("big_beak", make_chain(), cfg)
        qty = [lg.qty for lg in out["legs"]]
        assert qty == [1, -2, 1]

    def test_bw_iron_butterfly_no_upside_risk(self, cfg):
        out = build_strategy("bw_iron_butterfly", make_chain(base_iv=0.2), cfg, is_equity=False)
        assert out["analysis"]["upside_pl_at_expiry"] >= -0.01
        shorts = [lg.opt.strike for lg in out["legs"] if lg.qty < 0]
        assert len(set(shorts)) == 1

    def test_time_fly_upper_long_above_spot(self, cfg):
        ch = make_chain()
        out = build_strategy("time_fly", ch, cfg)
        assert max(lg.opt.strike for lg in out["legs"]) > ch.spot


class TestAnalyze:
    def test_pop_between_zero_and_one(self, cfg):
        out = build_strategy("dn_fly", make_chain(), cfg)
        a = analyze(out["legs"], make_chain())
        assert 0 < a["pop"] < 1
        assert len(a["breakevens"]) == 2


class TestExitAndSizing:
    def test_iron_duck_stop_is_double_credit(self, cfg):
        out = build_strategy("iron_duck", make_chain(base_iv=0.22), cfg, is_equity=False)
        plan = exit_plan("iron_duck", cfg, out, "20261016")
        assert plan["stop_close_debit"] == pytest.approx(2 * out["analysis"]["net_price"], abs=0.02)

    def test_fly_exit_levels(self, cfg):
        out = build_strategy("dn_fly", make_chain(), cfg)
        plan = exit_plan("dn_fly", cfg, out, "20261016")
        debit = -out["analysis"]["net_price"]
        assert plan["take_profit_close_credit"][0] == pytest.approx(debit * 1.2, abs=0.02)
        assert plan["stop_close_credit"] == pytest.approx(debit * 0.25, abs=0.02)
        assert plan["time_exit"] == "2026-10-15"

    def test_sizing_respects_5pct(self, cfg):
        out = build_strategy("dn_fly", make_chain(), cfg)
        s = size_position("dn_fly", cfg, out, 100_000, 100)
        assert s["contracts"] * s["max_loss_per_contract"] <= 5_000


class TestPositionPnl:
    def pos(self, cfg, name="iron_duck", base_iv=0.22):
        from trading_skills.multileg import legs_to_dict

        built = build_strategy(name, make_chain(base_iv=base_iv), cfg, is_equity=False)
        return {
            "symbol": "SPX",
            "expiry": "20261016",
            "strategy": name,
            "contracts": 2,
            "legs": legs_to_dict(built["legs"], "20261016"),
            "analysis": built["analysis"],
            "exit_plan": exit_plan(name, cfg, built, "20261016"),
        }

    def mids(self, pos, bump=0.0):
        from trading_skills.multileg import leg_key

        return {
            leg_key("SPX", pos["expiry"], lg["strike"], lg["right"]): lg["mid"] + bump
            for lg in pos["legs"]
        }

    def test_flat_marks_zero_pnl(self, cfg):
        from trading_skills.multileg import position_pnl

        p = self.pos(cfg)
        r = position_pnl(p, self.mids(p), 5000, "2026-10-01")
        assert r["pnl"] == 0
        assert r["pct_of_risk"] == 0
        assert r["risk"] == pytest.approx(p["analysis"]["max_loss"] * 200, abs=1)

    def test_credit_trade_all_legs_to_zero_is_max_profit(self, cfg):
        from trading_skills.multileg import leg_key, position_pnl

        p = self.pos(cfg)
        mids = {leg_key("SPX", p["expiry"], lg["strike"], lg["right"]): 0.0 for lg in p["legs"]}
        r = position_pnl(p, mids, 5200, "2026-10-01")
        assert r["pnl"] == pytest.approx(p["analysis"]["net_price"] * 200, abs=1)
        assert r["pct_of_max_profit"] == pytest.approx(100, abs=1)

    def test_iron_duck_stop_signal(self, cfg):
        from trading_skills.multileg import leg_key, position_pnl

        p = self.pos(cfg)
        credit = p["analysis"]["net_price"]
        mids = self.mids(p)
        short_put = next(lg for lg in p["legs"] if lg["right"] == "P" and lg["action"] == "SELL")
        mids[leg_key("SPX", p["expiry"], short_put["strike"], "P")] += 1.2 * credit
        r = position_pnl(p, mids, 4800, "2026-10-01")
        assert any(s.startswith("STOP") for s in r["signals"])
        assert r["pct_of_risk"] < 0

    def test_fly_time_exit(self, cfg):
        from trading_skills.multileg import position_pnl

        p = self.pos(cfg, "dn_fly", 0.16)
        r = position_pnl(p, self.mids(p), 5000, "2026-10-15")
        assert any(s.startswith("TIME EXIT") for s in r["signals"])

    def test_missing_mark(self, cfg):
        from trading_skills.multileg import position_pnl

        p = self.pos(cfg)
        r = position_pnl(p, {}, 5000, "2026-10-01")
        assert r["missing"] is True

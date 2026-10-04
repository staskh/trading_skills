# ABOUTME: Multi-leg options strategy engine (Iron Duck, butterflies, woodpeckers, Time Fly).
# ABOUTME: Pure logic: regime classification, strike selection by delta, validation, exit plans.

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from scipy.stats import norm

from trading_skills.black_scholes import black_scholes_price

BUTTERFLY_FAMILY = {
    "dn_fly",
    "bull_fly",
    "bear_fly",
    "bull_bwb",
    "bear_bwb",
    "neutral_bwb",
    "big_beak",
    "small_beak",
    "flat_head",
    "time_fly",
}
CREDIT_STRATEGIES = {"iron_duck", "reverse_iron_duck", "bw_iron_butterfly", "jade_lizard"}

# Selection matrix (doc §4): (direction, iv_level) -> strategies in priority order.
MATRIX = {
    ("NEUTRAL", "HIGH"): ["iron_duck", "flat_head"],
    ("NEUTRAL", "MID"): ["dn_fly", "flat_head", "time_fly"],
    ("NEUTRAL", "LOW"): ["dn_fly"],
    ("BULL", "HIGH"): ["iron_duck"],
    ("BULL", "MID"): ["bull_fly", "bull_bwb"],
    ("BULL", "LOW"): ["bull_fly"],
    ("BEAR", "HIGH"): ["big_beak", "bear_fly"],
    ("BEAR", "MID"): ["bear_fly", "small_beak", "time_fly"],
    ("BEAR", "LOW"): ["bear_fly"],
}


# ---------------------------------------------------------------- data types


@dataclass
class Opt:
    strike: float
    right: str  # "C" or "P"
    bid: float | None
    ask: float | None
    delta: float | None  # signed
    iv: float | None  # decimal, e.g. 0.18

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid:
            return (self.bid + self.ask) / 2
        return None

    @property
    def abs_delta(self) -> float | None:
        return abs(self.delta) if self.delta is not None else None


@dataclass
class Leg:
    qty: int  # +buy / -sell
    opt: Opt


class Chain:
    """One expiry's calls and puts, sorted by strike."""

    def __init__(self, options: list[Opt], spot: float, t_years: float, r: float = 0.04):
        self.spot = spot
        self.t = t_years
        self.r = r
        self.by_right = {
            "C": sorted([o for o in options if o.right == "C"], key=lambda o: o.strike),
            "P": sorted([o for o in options if o.right == "P"], key=lambda o: o.strike),
        }

    def _usable(self, right: str) -> list[Opt]:
        return [o for o in self.by_right[right] if o.mid is not None and o.delta is not None]

    def at_delta(self, right: str, target: float, shift: int = 0) -> Opt | None:
        opts = self._usable(right)
        if not opts:
            return None
        i = min(range(len(opts)), key=lambda k: abs(opts[k].abs_delta - target))
        j = i + shift
        return opts[j] if 0 <= j < len(opts) else None

    def offset(self, opt: Opt, n: int) -> Opt | None:
        opts = self._usable(opt.right)
        strikes = [o.strike for o in opts]
        if opt.strike not in strikes:
            return None
        j = strikes.index(opt.strike) + n
        return opts[j] if 0 <= j < len(opts) else None

    def at_strike(self, right: str, strike: float) -> Opt | None:
        opts = self._usable(right)
        if not opts:
            return None
        return min(opts, key=lambda o: abs(o.strike - strike))

    def first_above(self, right: str, price: float) -> Opt | None:
        for o in self._usable(right):
            if o.strike > price:
                return o
        return None

    def atm_iv(self) -> float | None:
        ivs = []
        for right in ("C", "P"):
            o = self.at_delta(right, 0.50)
            if o and o.iv:
                ivs.append(o.iv)
        return sum(ivs) / len(ivs) if ivs else None

    def atm_straddle(self) -> float | None:
        c = self.at_strike("C", self.spot)
        p = self.at_strike("P", self.spot)
        if c and p:
            return c.mid + p.mid
        return None


# ---------------------------------------------------------------- regime


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    alpha = 2 / (span + 1)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def classify_regime(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    iv_series: list[float],
    cfg: dict,
    chain: Chain | None = None,
    earnings: bool = False,
) -> dict:
    """Classify direction, IV level, IV trend and skew (doc §3)."""
    rc = cfg["regime"]
    d = rc["direction"]
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs, dtype=float)
    lo = np.asarray(lows, dtype=float)

    direction = "NEUTRAL"
    detail = {}
    if len(c) >= d["slow_ema"]:
        fast = _ema(c, d["fast_ema"])
        slow = _ema(c, d["slow_ema"])
        prev_c = np.concatenate([[c[0]], c[:-1]])
        tr = np.maximum(h - lo, np.maximum(abs(h - prev_c), abs(lo - prev_c)))
        atr = float(np.mean(tr[-14:]))
        slope = float(fast[-1] - fast[-5])
        band = d["neutral_atr_band"] * atr
        in_band = abs(c[-1] - fast[-1]) <= band
        if not in_band and c[-1] > fast[-1] and fast[-1] > slow[-1] and slope > 0:
            direction = "BULL"
        elif not in_band and c[-1] < fast[-1] and fast[-1] < slow[-1] and slope < 0:
            direction = "BEAR"
        detail = {
            "close": round(float(c[-1]), 2),
            "ema_fast": round(float(fast[-1]), 2),
            "ema_slow": round(float(slow[-1]), 2),
            "ema_fast_slope_5d": round(slope, 2),
            "atr14": round(atr, 2),
        }

    iv_level, iv_trend, ivr, iv_now = "MID", "FLAT", None, None
    ivs = [v for v in iv_series if v is not None and v > 0]
    if len(ivs) >= 2:
        iv_now = ivs[-1]
        lo_iv, hi_iv = min(ivs), max(ivs)
        ivr = 100 * (iv_now - lo_iv) / (hi_iv - lo_iv) if hi_iv > lo_iv else 50.0
        iv_level = "HIGH" if ivr >= rc["ivr_high"] else "LOW" if ivr < rc["ivr_low"] else "MID"
        chg = 100 * (iv_now / ivs[-2] - 1)
        band = rc["iv_flat_band_pct"]
        iv_trend = "EXPANDING" if chg > band else "CONTRACTING" if chg < -band else "FLAT"

    call_rich = False
    if chain is not None:
        sk = rc["call_rich_skew"]
        c25 = chain.at_delta("C", sk["call_delta"])
        p25 = chain.at_delta("P", sk["put_delta"])
        if c25 and p25 and c25.iv and p25.iv:
            call_rich = bool(c25.iv > p25.iv)

    return {
        "direction": direction,
        "iv_level": iv_level,
        "iv_trend": iv_trend,
        "iv_rank": round(ivr, 1) if ivr is not None else None,
        "iv_now": round(iv_now, 4) if iv_now is not None else None,
        "call_rich": call_rich,
        "earnings": earnings,
        "detail": detail,
    }


def select_strategies(regime: dict, portfolio_too_long: bool = False) -> list[str]:
    """Map a regime to candidate strategies in priority order (doc §4)."""
    if regime["earnings"]:
        return ["iron_duck"]
    names = list(MATRIX[(regime["direction"], regime["iv_level"])])
    if regime["call_rich"] and regime["iv_level"] != "LOW":
        names.insert(0, "reverse_iron_duck")
    if portfolio_too_long and "iron_duck" in names:
        names.remove("iron_duck")
        names.insert(0, "iron_duck")
    return names


def gate(name: str, regime: dict) -> str | None:
    """Return a reason the strategy is gated off, or None."""
    if name == "time_fly" and regime["iv_trend"] != "EXPANDING":
        return "Time Fly entry requires IV EXPANDING"
    if name in BUTTERFLY_FAMILY and regime["iv_trend"] == "CONTRACTING":
        return "butterfly-family entry requires IV FLAT or EXPANDING"
    return None


# ---------------------------------------------------------------- P/L math


def net_price(legs: list[Leg]) -> float:
    """Positive = credit received, negative = debit paid (per share, at mid)."""
    return sum(-leg.qty * leg.opt.mid for leg in legs)


def _intrinsic(opt: Opt, s: float) -> float:
    return max(0.0, s - opt.strike) if opt.right == "C" else max(0.0, opt.strike - s)


def pl_at_expiry(legs: list[Leg], s: float) -> float:
    return sum(leg.qty * (_intrinsic(leg.opt, s) - leg.opt.mid) for leg in legs)


def pl_theoretical(legs: list[Leg], s: float, t: float, r: float, fallback_iv: float) -> float:
    """Mark-to-model P/L if the underlying were at `s` right now."""
    total = 0.0
    for leg in legs:
        o = leg.opt
        iv = o.iv or fallback_iv
        kind = "call" if o.right == "C" else "put"
        total += leg.qty * (black_scholes_price(s, o.strike, t, r, iv, kind) - o.mid)
    return total


def analyze(legs: list[Leg], chain: Chain) -> dict:
    """Risk profile: credit/debit, max profit/loss, breakevens, POP, tail risk."""
    spot, t, r = chain.spot, chain.t, chain.r
    sigma = chain.atm_iv() or 0.25
    sd = sigma * math.sqrt(max(t, 1 / 365))
    strikes = [leg.opt.strike for leg in legs]
    lo = min(min(strikes) * 0.8, spot * math.exp(-6 * sd))
    hi = max(max(strikes) * 1.2, spot * math.exp(6 * sd))
    grid = np.unique(np.concatenate([np.linspace(lo, hi, 4001), strikes]))
    pl = np.array([pl_at_expiry(legs, s) for s in grid])

    # Lognormal probability mass per grid cell
    edges = np.concatenate([[0.0], (grid[1:] + grid[:-1]) / 2, [np.inf]])
    mu = math.log(spot) + (r - 0.5 * sigma**2) * t
    with np.errstate(divide="ignore"):
        z = (np.log(edges) - mu) / sd
    mass = np.diff(norm.cdf(z))
    pop = float(mass[pl > 1e-9].sum())

    bes = []
    for i in range(len(grid) - 1):
        a, b = pl[i], pl[i + 1]
        if (a < 0 <= b) or (a >= 0 > b):
            bes.append(float(grid[i] + (grid[i + 1] - grid[i]) * (-a) / (b - a)))

    credit = net_price(legs)
    upside_pl = pl_at_expiry(legs, max(strikes) * 10)
    downside_pl = pl_at_expiry(legs, 1e-6)
    down_be = min(bes) if bes else None
    loss_at_down_be = -pl_theoretical(legs, down_be, t, r, sigma) if down_be is not None else None
    return {
        "net_price": round(credit, 2),
        "price_type": "credit" if credit >= 0 else "debit",
        "max_profit": round(float(max(pl.max(), upside_pl, downside_pl)), 2),
        "max_loss": round(float(-min(pl.min(), upside_pl, downside_pl)), 2),
        "breakevens": [round(b, 2) for b in bes],
        "pop": round(pop, 4),
        "upside_pl_at_expiry": round(upside_pl, 2),
        "downside_pl_at_expiry": round(downside_pl, 2),
        "theoretical_loss_at_downside_be": (
            round(loss_at_down_be, 2) if loss_at_down_be is not None else None
        ),
        "atm_iv_used": round(sigma, 4),
    }


# ---------------------------------------------------------------- builders
# Each builder: (chain, cfg_for_strategy, shifts) -> list[Leg] | None.
# `shifts` maps a named anchor to a strike-index offset used by the strike search.


def _legs_ok(legs) -> bool:
    return legs is not None and all(leg.opt is not None for leg in legs)


def _mirror(ch: Chain, right: str, body: Opt, wing: Opt) -> Opt | None:
    return ch.at_strike(right, 2 * body.strike - wing.strike)


def _leg_delta(cfg: dict, i: int, default: float) -> float:
    try:
        return float(cfg["legs"][i]["delta"])
    except (KeyError, IndexError, TypeError):
        return default


def build_iron_duck(ch, cfg, s):
    sc = ch.at_delta("C", _leg_delta(cfg, 0, 0.65), s.get("sc", 0))
    if sc is None:
        return None
    lc = ch.offset(sc, max(1, cfg["legs"][1].get("offset_strikes", 1) + s.get("lc", 0)))
    sp = ch.at_delta("P", _leg_delta(cfg, 2, 0.15), s.get("sp", 0))
    lp = ch.at_delta("P", _leg_delta(cfg, 3, 0.10), s.get("lp", 0))
    legs = [Leg(-1, sc), Leg(1, lc), Leg(-1, sp), Leg(1, lp)]
    if not _legs_ok(legs) or not (lp.strike < sp.strike and sc.strike < lc.strike):
        return None
    return legs


def build_reverse_iron_duck(ch, cfg, s):
    sp = ch.at_delta("P", _leg_delta(cfg, 0, 0.65), s.get("sp", 0))
    if sp is None:
        return None
    lp = ch.offset(sp, -max(1, -cfg["legs"][1].get("offset_strikes", -1) + s.get("lp", 0)))
    sc = ch.at_delta("C", _leg_delta(cfg, 2, 0.15), s.get("sc", 0))
    lc = ch.at_delta("C", _leg_delta(cfg, 3, 0.10), s.get("lc", 0))
    legs = [Leg(-1, sp), Leg(1, lp), Leg(-1, sc), Leg(1, lc)]
    if not _legs_ok(legs) or not (lp.strike < sp.strike and sc.strike < lc.strike):
        return None
    return legs


def build_bw_iron_butterfly(ch, cfg, s):
    sc = ch.at_delta("C", _leg_delta(cfg, 0, 0.52), s.get("body", 0))
    if sc is None:
        return None
    sp = ch.at_strike("P", sc.strike)
    if sp is None or sp.strike != sc.strike:
        return None
    mult = float(cfg["legs"][3].get("width_mult_of_call_wing", 2.5))
    best = None
    for n in range(1, 41):  # widest call wing whose credit still covers it
        lc = ch.offset(sc, n)
        if lc is None:
            break
        width = lc.strike - sc.strike
        lp = ch.offset(ch.at_strike("P", sc.strike - mult * width), s.get("pw", 0))
        if lp is None or lp.strike >= sp.strike:
            continue
        legs = [Leg(-1, sc), Leg(-1, sp), Leg(1, lc), Leg(1, lp)]
        if net_price(legs) >= width:
            best = legs
    return best


def build_jade_lizard(ch, cfg, s):
    sc = ch.at_delta("C", _leg_delta(cfg, 0, 0.65), s.get("sc", 0))
    if sc is None:
        return None
    lc = ch.offset(sc, max(1, 1 + s.get("lc", 0)))
    sp = ch.at_delta("P", _leg_delta(cfg, 2, 0.15), s.get("sp", 0))
    legs = [Leg(-1, sc), Leg(1, lc), Leg(-1, sp)]
    return legs if _legs_ok(legs) and sc.strike < lc.strike else None


def build_dn_fly(ch, cfg, s):
    body = ch.at_delta("C", _leg_delta(cfg, 0, 0.50), s.get("body", 0))
    upper = ch.at_delta("C", _leg_delta(cfg, 1, 0.25), s.get("wing", 0))
    if body is None or upper is None or upper.strike <= body.strike:
        return None
    lower = _mirror(ch, "C", body, upper)
    legs = [Leg(1, lower), Leg(-2, body), Leg(1, upper)]
    return legs if _legs_ok(legs) and lower.strike < body.strike else None


def _directional_fly(ch, cfg, s, right):
    body = ch.at_delta(right, _leg_delta(cfg, 0, 0.30), s.get("body", 0))
    inner = ch.at_delta(right, _leg_delta(cfg, 1, 0.45), s.get("wing", 0))
    if body is None or inner is None or inner.strike == body.strike:
        return None
    outer = _mirror(ch, right, body, inner)
    legs = [Leg(1, inner), Leg(-2, body), Leg(1, outer)]
    if not _legs_ok(legs) or outer.strike == body.strike:
        return None
    return sorted(legs, key=lambda leg: leg.opt.strike)


def build_bull_fly(ch, cfg, s):
    return _directional_fly(ch, cfg, s, "C")


def build_bear_fly(ch, cfg, s):
    return _directional_fly(ch, cfg, s, "P")


def _bwb(ch, cfg, s, right):
    body = ch.at_delta(right, _leg_delta(cfg, 0, 0.30), s.get("body", 0))
    near = ch.at_delta(right, _leg_delta(cfg, 1, 0.45), s.get("near", 0))
    if body is None or near is None or near.strike == body.strike:
        return None
    mult = cfg["legs"][2].get("far_wing_mult", [1.5, 2.0])
    mult = mult[0] if isinstance(mult, list) else float(mult)
    target = body.strike + mult * (body.strike - near.strike)
    far = ch.at_strike(right, target)
    far = ch.offset(far, s.get("far", 0)) if far else None
    legs = [Leg(1, near), Leg(-2, body), Leg(1, far)]
    if not _legs_ok(legs) or far.strike == body.strike:
        return None
    return sorted(legs, key=lambda leg: leg.opt.strike)


def build_bull_bwb(ch, cfg, s):
    return _bwb(ch, cfg, s, "C")


def build_bear_bwb(ch, cfg, s):
    return _bwb(ch, cfg, s, "P")


def build_neutral_bwb(ch, cfg, s):
    body = ch.at_delta("P", _leg_delta(cfg, 0, 0.50), s.get("body", 0))
    ref = ch.at_delta("C", 0.25)  # wing unit = distance to the 25-delta call (as dn_fly)
    if body is None or ref is None or ref.strike <= body.strike:
        return None
    w = ref.strike - body.strike
    below = cfg["legs"][2].get("width_units_below", [1.5, 2.0])
    below = below[0] if isinstance(below, list) else float(below)
    upper = ch.at_strike("P", body.strike + w)
    lower = ch.at_strike("P", body.strike - below * w)
    lower = ch.offset(lower, s.get("far", 0)) if lower else None
    legs = [Leg(1, lower), Leg(-2, body), Leg(1, upper)]
    if not _legs_ok(legs) or not (lower.strike < body.strike < upper.strike):
        return None
    return legs


def _put_deltas(ch, cfg, s, defaults):
    legs = []
    for i, (qty, d) in enumerate(defaults):
        leg_cfg = cfg["legs"][i] if i < len(cfg.get("legs", [])) else {}
        sign = -1 if leg_cfg.get("action", "buy" if qty > 0 else "sell") == "sell" else 1
        n = int(leg_cfg.get("qty", abs(qty)))
        legs.append(Leg(sign * n, ch.at_delta("P", leg_cfg.get("delta", d), s.get(f"l{i}", 0))))
    if not _legs_ok(legs):
        return None
    strikes = [leg.opt.strike for leg in legs]
    if len(set(strikes)) != len(strikes):
        return None
    return sorted(legs, key=lambda leg: leg.opt.strike)


def build_big_beak(ch, cfg, s):
    return _put_deltas(ch, cfg, s, [(1, 0.50), (-2, 0.42), (1, 0.30)])


def build_small_beak(ch, cfg, s):
    return _put_deltas(ch, cfg, s, [(1, 0.48), (-2, 0.40), (1, 0.30)])


def build_flat_head(ch, cfg, s):
    return _put_deltas(ch, cfg, s, [(1, 0.50), (-1, 0.43), (-1, 0.28), (1, 0.20)])


def build_time_fly(ch, cfg, s):
    fly = cfg["fly"]["legs"]
    body = ch.at_delta("P", fly[1].get("delta", 0.30), s.get("body", 0))
    upper = ch.first_above("P", ch.spot)
    if body is None or upper is None:
        return None
    upper = ch.offset(upper, s.get("upper", 0))
    if upper is None or upper.strike <= body.strike:
        return None
    lower = ch.at_strike("P", body.strike - (upper.strike - body.strike))
    lower = ch.offset(lower, -abs(s.get("far", 0))) if lower else None
    legs = [Leg(1, lower), Leg(-2, body), Leg(1, upper)]
    if not _legs_ok(legs) or lower.strike >= body.strike:
        return None
    return legs


BUILDERS = {
    "iron_duck": (build_iron_duck, ["sp", "lp", "sc", "lc"]),
    "reverse_iron_duck": (build_reverse_iron_duck, ["sc", "lc", "sp", "lp"]),
    "bw_iron_butterfly": (build_bw_iron_butterfly, ["body", "pw"]),
    "jade_lizard": (build_jade_lizard, ["sp", "sc", "lc"]),
    "dn_fly": (build_dn_fly, ["wing", "body"]),
    "bull_fly": (build_bull_fly, ["wing", "body"]),
    "bear_fly": (build_bear_fly, ["wing", "body"]),
    "bull_bwb": (build_bull_bwb, ["far", "near", "body"]),
    "bear_bwb": (build_bear_bwb, ["far", "near", "body"]),
    "neutral_bwb": (build_neutral_bwb, ["far", "body"]),
    "big_beak": (build_big_beak, ["l0", "l2", "l1"]),
    "small_beak": (build_small_beak, ["l0", "l2", "l1"]),
    "flat_head": (build_flat_head, ["l0", "l3", "l1", "l2"]),
    "time_fly": (build_time_fly, ["far", "upper", "body"]),
}


# ---------------------------------------------------------------- validation


def validate(name: str, cfg: dict, legs: list[Leg], a: dict, is_equity: bool) -> dict:
    """Run the strategy's entry checks. Returns {check: bool}."""
    v = cfg.get("validate", {})
    checks = {}
    credit = a["net_price"]
    strikes = sorted(leg.opt.strike for leg in legs)
    widest = max((b - x for x, b in zip(strikes, strikes[1:])), default=0)
    tol = 0.01

    if "min_pop" in v:
        checks["pop_ok"] = a["pop"] >= v["min_pop"]
    if "pop" in v:
        checks["pop_ok"] = a["pop"] >= v["pop"][0]
    if v.get("no_upside_risk"):
        checks["no_upside_risk"] = a["upside_pl_at_expiry"] >= -tol
    if v.get("no_downside_risk"):
        checks["no_downside_risk"] = a["downside_pl_at_expiry"] >= -tol
    if v.get("loss_at_be_le_credit"):
        loss = a["theoretical_loss_at_downside_be"]
        checks["loss_at_be_le_credit"] = loss is not None and loss <= credit + tol
    if "min_credit_equity" in v and is_equity:
        checks["min_credit"] = credit >= v["min_credit_equity"]
    if v.get("small_credit_or_debit") or cfg.get("entry_price", {}).get("small_credit_or_debit"):
        checks["small_credit_or_debit"] = abs(credit) <= 0.10 * widest
    if v.get("beak_profit_gt_loss_at_downside_be"):
        loss = a["theoretical_loss_at_downside_be"]
        checks["beak_gt_loss_at_be"] = loss is not None and a["max_profit"] > loss
    if v.get("credit_gt_call_width"):
        calls = sorted(leg.opt.strike for leg in legs if leg.opt.right == "C")
        checks["credit_gt_call_width"] = credit > (calls[-1] - calls[0])
    ep = cfg.get("entry_price", {})
    if "max_debit_pct_near_width" in ep:
        near_w = (
            abs(legs[1].opt.strike - legs[0].opt.strike)
            if name != "bear_bwb"
            else abs(legs[2].opt.strike - legs[1].opt.strike)
        )
        max_debit = ep["max_debit_pct_near_width"] / 100 * near_w
        checks["entry_price_ok"] = credit >= 0 or -credit <= max_debit
    if name in ("dn_fly", "bull_fly", "bear_fly", "time_fly"):
        checks["is_debit"] = credit < 0
    if name == "dn_fly" and "width_check_x_straddle" in cfg:
        # Wing width vs the expected move (ATM straddle)
        lo_x, hi_x = cfg["width_check_x_straddle"]
        width = legs[2].opt.strike - legs[1].opt.strike
        straddle = a.get("_straddle")
        if straddle:
            checks["width_vs_expected_move"] = lo_x * straddle <= width <= hi_x * straddle
    return checks


# ---------------------------------------------------------------- search


def _shift_candidates(params: list[str], max_attempts: int) -> list[dict]:
    """Base plus single-anchor moves of ±1, ±2 strikes, in that order."""
    cands = [{}]
    for step in (1, -1, 2, -2):
        for p in params:
            cands.append({p: step})
    return cands[: 1 + max_attempts * 2]


def build_strategy(name: str, chain: Chain, cfg: dict, is_equity: bool = True) -> dict:
    """Build, analyze and validate one strategy, searching nearby strikes."""
    scfg = cfg["strategies"][name]
    builder, params = BUILDERS[name]
    max_attempts = cfg.get("strike_search", {}).get("max_attempts", 6)
    straddle = chain.atm_straddle()

    best = None
    for shifts in _shift_candidates(params, max_attempts):
        legs = builder(chain, scfg, shifts)
        if not legs:
            continue
        a = analyze(legs, chain)
        a["_straddle"] = straddle
        checks = validate(name, scfg, legs, a, is_equity)
        a.pop("_straddle")
        passed = all(checks.values())
        score = sum(checks.values())
        if (
            best is None
            or (passed and not best["passed"])
            or (not best["passed"] and score > best["_score"])
        ):
            best = {
                "strategy": name,
                "passed": passed,
                "legs": legs,
                "analysis": a,
                "checks": checks,
                "strike_shifts": shifts,
                "_score": score,
            }
        if passed:
            break
    if best is None:
        return {"strategy": name, "passed": False, "error": "could not build legs from chain"}
    best.pop("_score")
    return best


# ---------------------------------------------------------------- exits & sizing


def exit_plan(name: str, cfg: dict, built: dict, expiry: str) -> dict:
    """Concrete exit levels in combo price / underlying price terms."""
    scfg = cfg["strategies"][name]
    ex = scfg.get("exit", {})
    a = built["analysis"]
    credit = a["net_price"]
    exp_date = datetime.strptime(expiry, "%Y%m%d").date()
    one_dte = (exp_date - timedelta(days=1)).strftime("%Y-%m-%d")
    down_be = a["breakevens"][0] if a["breakevens"] else None
    plan = {"adjustments": scfg.get("adjustments", name in BUTTERFLY_FAMILY)}

    if name in CREDIT_STRATEGIES:
        stop_pct = ex.get("stop_loss_pct_credit", 100) / 100
        plan.update(
            {
                "stop_close_debit": round(credit * (1 + stop_pct), 2),
                "stop_rule": f"close manually when loss reaches {int(stop_pct * 100)}% of credit",
                "alert_underlying_at": down_be,
                "otherwise": "hold to expiry; close on expiry day if a short leg is ITM and its "
                "long partner is OTM (equities/futures)",
            }
        )
    elif name in ("dn_fly", "bull_fly", "bear_fly"):
        debit = -credit
        pt = ex.get("pt_pct_debit", [20, 30])
        plan.update(
            {
                "take_profit_close_credit": [round(debit * (1 + p / 100), 2) for p in pt],
                "stop_close_credit": round(debit * (1 - ex.get("stop_pct_debit", 75) / 100), 2),
                "time_exit": one_dte,
            }
        )
    elif name in ("bull_bwb", "bear_bwb", "neutral_bwb"):
        pt = ex.get("pt_pct_max_profit", [20, 30])
        plan.update(
            {
                "take_profit_pl": [round(a["max_profit"] * p / 100, 2) for p in pt],
                "stop_pl": round(-a["max_loss"] * ex.get("stop_pct_max_risk", 75) / 100, 2),
                "time_exit": one_dte,
            }
        )
    elif name in ("big_beak", "small_beak", "flat_head"):
        plan.update(
            {
                "exit_if_underlying_near": down_be,
                "scale_out_pl": [
                    round(a["max_loss"] * p / 100, 2) for p in ex.get("scale_out_pct", [20, 30, 40])
                ],
                "scale_out_basis": "percent of max risk [A]",
                "time_exit": one_dte,
            }
        )
    elif name == "time_fly":
        pt = ex.get("pt_pct_max_risk", [5, 10])
        adj = scfg.get("adj_calendar", {})
        upper = max(leg.opt.strike for leg in built["legs"])
        cal_legs = adj.get("legs", [{}, {}])
        cal_delta = cal_legs[0].get("delta", 0.40)
        cal_gap = cal_legs[1].get("expiry_gap_dte", [1, 7])
        plan.update(
            {
                "take_profit_pl": [round(a["max_loss"] * p / 100, 2) for p in pt],
                "loss_review_pl": round(-a["max_loss"] * ex.get("loss_review_pct", 15) / 100, 2),
                "exit_if_underlying_near": down_be,
                "time_exit": one_dte,
                "calendar_adjustment": {
                    "trigger_underlying_above": upper,
                    "action": f"sell ~{cal_delta} delta call (this expiry) / buy same strike "
                    f"{cal_gap} DTE later, at end of day",
                    "max_adds": adj.get("max_adds", 2),
                },
            }
        )
    if name in BUTTERFLY_FAMILY and name != "time_fly":
        plan["adjustments"] = cfg["strategies"].get("fly_adjustments", {})
    return plan


def size_position(name: str, cfg: dict, built: dict, account_value: float, mult: int) -> dict:
    risk = cfg["risk"]
    pct = risk["fly_max_pct_per_position"]  # [A] also used per Iron Duck position
    max_loss = built["analysis"]["max_loss"] * mult
    if max_loss <= 0:
        return {"contracts": 0, "note": "no max loss computed"}
    contracts = int(account_value * pct / 100 // max_loss)
    return {
        "contracts": contracts,
        "max_loss_per_contract": round(max_loss, 2),
        "risk_budget": round(account_value * pct / 100, 2),
    }


def legs_to_dict(legs: list[Leg], expiry: str) -> list[dict]:
    return [
        {
            "action": "BUY" if leg.qty > 0 else "SELL",
            "qty": abs(leg.qty),
            "right": leg.opt.right,
            "strike": leg.opt.strike,
            "expiry": expiry,
            "delta": round(leg.opt.delta, 3) if leg.opt.delta is not None else None,
            "iv": round(leg.opt.iv, 4) if leg.opt.iv else None,
            "bid": leg.opt.bid,
            "ask": leg.opt.ask,
            "mid": round(leg.opt.mid, 2),
        }
        for leg in legs
    ]


def combo_spread_ok(legs: list[Leg], cfg: dict) -> dict:
    """Liquidity check on leg and combo bid/ask widths (doc §2)."""
    liq = cfg["universe"]["liquidity"]
    leg_pcts = []
    for leg in legs:
        o = leg.opt
        leg_pcts.append(100 * (o.ask - o.bid) / o.mid if o.mid else float("inf"))
    combo_w = sum(abs(leg.qty) * (leg.opt.ask - leg.opt.bid) for leg in legs)
    combo_mid = abs(net_price(legs))
    widest = max(leg_pcts)
    return {
        "max_leg_spread_pct": round(widest, 1),
        "combo_spread": round(combo_w, 2),
        "leg_spreads_ok": widest <= liq["max_leg_spread_pct_mid"],
        "combo_spread_pct_of_mid": round(100 * combo_w / combo_mid, 1) if combo_mid else None,
    }


# ---------------------------------------------------------------- position monitoring


def leg_key(symbol: str, expiry: str, strike: float, right: str) -> str:
    return f"{symbol}|{expiry}|{float(strike):g}|{right}"


def position_pnl(pos: dict, mids: dict, spot: float | None, today: str, mult: int = 100) -> dict:
    """Mark a tracked position: P/L in $ and as % of max risk, plus exit-plan signals.

    pos holds the proposal fields: symbol, expiry, strategy, contracts, legs (with entry mid),
    analysis (net_price, max_loss, max_profit) and exit_plan. `today` is YYYY-MM-DD.
    """
    contracts = pos.get("contracts", 1)
    pnl_ps, value = 0.0, 0.0
    for leg in pos["legs"]:
        now = mids.get(leg_key(pos["symbol"], pos["expiry"], leg["strike"], leg["right"]))
        if now is None:
            return {"pnl": None, "pct_of_risk": None, "signals": ["NO MARK"], "missing": True}
        signed = leg["qty"] if leg["action"] == "BUY" else -leg["qty"]
        pnl_ps += signed * (now - leg["mid"])
        value += signed * now

    a = pos["analysis"]
    risk = a["max_loss"] * mult * contracts
    pnl = pnl_ps * mult * contracts
    plan = pos.get("exit_plan", {})
    credit = a["net_price"]
    signals = []

    if "stop_close_debit" in plan and -value >= plan["stop_close_debit"]:
        signals.append("STOP: loss reached stop % of credit")
    if "take_profit_close_credit" in plan and value >= min(plan["take_profit_close_credit"]):
        signals.append("TARGET: profit target reached")
    if "stop_close_credit" in plan and value <= plan["stop_close_credit"]:
        signals.append("STOP: loss exceeds stop % of debit")
    for key, label in (("take_profit_pl", "TARGET"), ("scale_out_pl", "SCALE OUT")):
        if key in plan and plan[key] and pnl_ps >= min(plan[key]):
            signals.append(f"{label}: P/L reached {min(plan[key]):.2f}/sh")
    for key in ("stop_pl", "loss_review_pl"):
        if key in plan and plan[key] is not None and pnl_ps <= plan[key]:
            signals.append(f"STOP: P/L below {plan[key]:.2f}/sh")
    level = plan.get("alert_underlying_at") or plan.get("exit_if_underlying_near")
    if spot and level and spot <= level * 1.005:
        signals.append(f"ALERT: underlying {spot:.2f} near downside break-even {level:.2f}")
    cal = plan.get("calendar_adjustment")
    if spot and cal and spot > cal["trigger_underlying_above"]:
        signals.append("ADJUST: price above upper long, add call calendar")
    if plan.get("time_exit") and today >= plan["time_exit"]:
        signals.append(f"TIME EXIT: {plan['time_exit']}")
    if credit > 0 and "stop_close_debit" in plan and today >= _iso(pos["expiry"]):
        signals.append("EXPIRY DAY: close if a short leg is ITM")

    return {
        "pnl_per_share": round(pnl_ps, 2),
        "pnl": round(pnl, 2),
        "risk": round(risk, 2),
        "pct_of_risk": round(100 * pnl / risk, 1) if risk else None,
        "pct_of_max_profit": (
            round(100 * pnl_ps / a["max_profit"], 1) if a.get("max_profit") else None
        ),
        "current_value": round(value, 2),
        "signals": signals,
        "missing": False,
    }


def _iso(expiry: str) -> str:
    return f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"

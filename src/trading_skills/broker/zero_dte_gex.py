# ABOUTME: Gamma-exposure (GEX) profile for a 0DTE chain: net GEX, gamma flip, call/put walls.
# ABOUTME: Pure functions over quoted legs — regime gate + strike guidance for credit spreads.

import math

from trading_skills.black_scholes import black_scholes_gamma

CONTRACT_MULTIPLIER = 100  # index and equity options alike

# Dealer-positioning convention: customers buy puts for protection and sell/overwrite
# calls, so dealers are assumed LONG call gamma and SHORT put gamma. Net GEX is
# therefore (call gamma) - (put gamma), weighted by the size at each strike. This
# assumption is the model's weakest link — heavy retail call buying inverts the call
# side's sign and the whole profile with it.
#
# Positive net GEX -> dealers hedge against the move (sell rallies, buy dips): vol is
# suppressed, price mean-reverts and pins. Negative -> they hedge with the move: moves
# amplify, trends run. Short premium wants the positive regime.

# Below this |net GEX| (dollars per 1% move) the book is too balanced to call a regime.
NEUTRAL_BAND = 5e7  # $50M per 1%

# How far the flip-level scan ranges around spot, and at how many points.
_FLIP_BAND = 0.05
_FLIP_STEPS = 81


def strike_gex(gamma: float, weight: float, spot: float, multiplier: int = CONTRACT_MULTIPLIER):
    """Dollar gamma at one strike: the $ delta dealers must re-hedge per 1% spot move.

    gamma is per-share (per-point), weight is the contract count standing behind it
    (open interest or same-day volume).
    """
    return gamma * weight * multiplier * spot * spot * 0.01


def _weight_of(opt: dict, source: str):
    """Contract count standing behind a strike, per the chosen weighting source."""
    value = opt.get("volume") if source == "volume" else opt.get("open_interest")
    if value is None or value < 0:
        return None
    return float(value)


def resolve_weight_source(legs: list[dict], weight_by: str = "auto") -> str:
    """Pick the size measure behind each strike: same-day volume or open interest.

    'auto' prefers volume for 0DTE. IBKR's open interest is the PRIOR settlement's —
    for a same-day expiry most of the book is opened this morning, so prior-day OI
    systematically misses the flow that actually drives today's hedging. Volume is the
    honest same-day proxy; OI is the fallback when no volume has printed yet.
    """
    if weight_by in ("volume", "oi"):
        return weight_by
    has_volume = any((o.get("volume") or 0) > 0 for o in legs)
    return "volume" if has_volume else "oi"


def _gamma_at(opt: dict, spot: float, T: float | None, rate: float):
    """Gamma at `spot`: IBKR's model gamma at the live spot, else BS from the leg's IV.

    Re-deriving from IV is what lets the profile be re-evaluated at OTHER spot levels
    (the flip-level scan); at the live spot the broker's own gamma is preferred.
    """
    iv = opt.get("iv")
    if iv and iv > 0 and T and T > 0:
        return black_scholes_gamma(spot, opt["strike"], T, rate, iv)
    return None


def _net_gex_at(
    calls: list[dict],
    puts: list[dict],
    weights: dict,
    spot: float,
    T: float | None,
    rate: float,
    multiplier: int,
) -> float | None:
    """Net dealer GEX if spot were at `spot`, holding each strike's size/IV fixed.

    Only the gammas are re-evaluated — the position (weights) is what it is.
    """
    total = 0.0
    seen = False
    for legs, sign in ((calls, 1.0), (puts, -1.0)):
        for opt in legs:
            w = weights.get((opt["right"], opt["strike"]))
            if not w:
                continue
            g = _gamma_at(opt, spot, T, rate)
            if g is None:
                continue
            total += sign * strike_gex(g, w, spot, multiplier)
            seen = True
    return total if seen else None


def find_flip_level(
    calls: list[dict],
    puts: list[dict],
    weights: dict,
    spot: float,
    T: float | None,
    rate: float,
    multiplier: int = CONTRACT_MULTIPLIER,
) -> float | None:
    """The spot level where net GEX crosses zero — the gamma flip.

    Scans a grid around spot, re-deriving every strike's gamma via Black-Scholes at
    each level, and linearly interpolates the sign change nearest the current spot.
    Returns None if no crossing lies within the band (the book is one-sided there).
    """
    if not (T and T > 0):
        return None

    lo, hi = spot * (1 - _FLIP_BAND), spot * (1 + _FLIP_BAND)
    step = (hi - lo) / (_FLIP_STEPS - 1)
    grid = []
    for i in range(_FLIP_STEPS):
        s = lo + i * step
        g = _net_gex_at(calls, puts, weights, s, T, rate, multiplier)
        if g is not None:
            grid.append((s, g))
    if len(grid) < 2:
        return None

    crossings = []
    for (s0, g0), (s1, g1) in zip(grid, grid[1:]):
        if g0 == 0:
            crossings.append(s0)
        elif (g0 < 0) != (g1 < 0):
            crossings.append(s0 + (s1 - s0) * (-g0) / (g1 - g0))  # linear interpolation
    if not crossings:
        return None
    return min(crossings, key=lambda s: abs(s - spot))


def build_gex_profile(
    calls: list[dict],
    puts: list[dict],
    spot: float,
    *,
    T: float | None = None,
    rate: float = 0.045,
    weight_by: str = "auto",
    multiplier: int = CONTRACT_MULTIPLIER,
    top_strikes: int = 10,
) -> dict:
    """Dealer gamma-exposure profile for one expiry's chain.

    Needs BOTH sides (the net is calls minus puts), each leg carrying `gamma` (IBKR
    model greek) plus `volume`/`open_interest`. Returns net GEX, the gamma flip level,
    the call/put walls, and the per-strike ladder.

    All GEX figures are dollars of dealer delta per 1% move in the underlying.
    """
    legs = list(calls) + list(puts)
    if not legs or not spot or spot <= 0:
        return {"available": False, "reason": "No chain data for a GEX profile."}

    source = resolve_weight_source(legs, weight_by)

    weights = {}
    per_strike: dict[float, dict] = {}
    missing_gamma = 0
    missing_weight = 0
    derived_gamma = 0

    for opt, sign, key in [(o, 1.0, "call_gex") for o in calls] + [
        (o, -1.0, "put_gex") for o in puts
    ]:
        gamma = opt.get("gamma")
        if gamma is None or (isinstance(gamma, float) and math.isnan(gamma)):
            # IBKR streams model greeks only during RTH. Off-hours (--allow-stale) the
            # leg still carries an IV, so gamma is recoverable via Black-Scholes — the
            # same fallback delta/IV already take.
            gamma = _gamma_at(opt, spot, T, rate)
            if gamma is not None:
                derived_gamma += 1
        weight = _weight_of(opt, source)
        if gamma is None:
            missing_gamma += 1
            continue
        if not weight:
            missing_weight += 1
            continue
        strike = opt["strike"]
        weights[(opt["right"], strike)] = weight
        gex = strike_gex(gamma, weight, spot, multiplier)
        row = per_strike.setdefault(
            strike, {"strike": strike, "call_gex": 0.0, "put_gex": 0.0, "net_gex": 0.0}
        )
        row[key] = gex
        row["net_gex"] += sign * gex

    if not per_strike:
        return {
            "available": False,
            "reason": (
                "No strike carried both a gamma and a size (volume/open interest) — "
                "IBKR streams model greeks only during RTH with an options data "
                "entitlement."
            ),
            "weight_source": source,
        }

    ladder = sorted(per_strike.values(), key=lambda r: r["strike"])
    net_gex = sum(r["net_gex"] for r in ladder)

    # Walls: the heaviest gamma concentrations dealers hedge around. The call wall is
    # the largest call-gamma strike above spot (resistance), the put wall the largest
    # put-gamma strike below (support).
    above = [r for r in ladder if r["strike"] >= spot and r["call_gex"] > 0]
    below = [r for r in ladder if r["strike"] <= spot and r["put_gex"] > 0]
    call_wall = max(above, key=lambda r: r["call_gex"])["strike"] if above else None
    put_wall = max(below, key=lambda r: r["put_gex"])["strike"] if below else None

    flip = find_flip_level(calls, puts, weights, spot, T, rate, multiplier)

    if net_gex > NEUTRAL_BAND:
        regime = "positive_gamma"
    elif net_gex < -NEUTRAL_BAND:
        regime = "negative_gamma"
    else:
        regime = "neutral_gamma"

    heaviest = sorted(ladder, key=lambda r: abs(r["net_gex"]), reverse=True)[:top_strikes]

    caveats = [
        "GEX models dealer positioning (dealers assumed long calls / short puts); it "
        "is an estimate of the book, not a measurement of it.",
    ]
    if source == "volume":
        caveats.append(
            "Weighted by same-day VOLUME, not open interest: IBKR reports the prior "
            "settlement's OI, which misses the same-day flow that dominates a 0DTE "
            "book. Volume double-counts round-trips and cannot see whether a contract "
            "was opened or closed."
        )
    else:
        caveats.append(
            "Weighted by OPEN INTEREST, which for a 0DTE expiry is the PRIOR "
            "settlement's — it excludes everything opened today. Treat the walls as "
            "provisional until volume prints."
        )
    if flip is None:
        caveats.append(
            "No gamma flip within +/-5% of spot — the book is one-sided across the band."
        )
    if derived_gamma:
        caveats.append(
            f"{derived_gamma} leg(s) had no IBKR model gamma; it was derived from IV via "
            "Black-Scholes (off-hours). Preview only — not a live read of the book."
        )

    return {
        "available": True,
        "weight_source": source,
        "spot": round(spot, 2),
        "net_gex": round(net_gex, 0),
        "net_gex_bn": round(net_gex / 1e9, 3),
        "regime": regime,
        "flip_level": round(flip, 2) if flip is not None else None,
        "call_wall": call_wall,
        "put_wall": put_wall,
        "units": "dollars of dealer delta per 1% move in the underlying",
        "coverage": {
            "strikes": len(ladder),
            "missing_gamma": missing_gamma,
            "missing_weight": missing_weight,
            "derived_gamma": derived_gamma,  # Black-Scholes, not IBKR's model greek
        },
        "heaviest_strikes": [
            {
                "strike": r["strike"],
                "call_gex_bn": round(r["call_gex"] / 1e9, 3),
                "put_gex_bn": round(r["put_gex"] / 1e9, 3),
                "net_gex_bn": round(r["net_gex"] / 1e9, 3),
            }
            for r in heaviest
        ],
        "caveats": caveats,
    }


# --------------------------------------------------------------------------- #
# Regime gate + strike guidance
# --------------------------------------------------------------------------- #
_REGIME_NOTE = {
    "positive_gamma": (
        "Positive net GEX: dealers are long gamma and hedge AGAINST the move (sell "
        "rallies, buy dips). Realized vol is suppressed and price mean-reverts toward "
        "the big strikes — the supportive regime for short premium."
    ),
    "negative_gamma": (
        "Negative net GEX: dealers are short gamma and hedge WITH the move (sell into "
        "weakness, buy into strength). Moves get amplified and trends run — the regime "
        "that runs credit spreads over. Size down or stand aside."
    ),
    "neutral_gamma": (
        "Net GEX is near zero: the book is balanced and gives no regime edge either "
        "way. Trade the setup on its own merits."
    ),
}

# One notch down the timing scale per the regime gate.
_DOWNGRADE = {"best": "fair", "good": "fair", "fair": "avoid", "avoid": "avoid", "closed": "closed"}


def gex_guidance(profile: dict, spread_type: str, spot: float) -> dict:
    """Regime read + short-strike guidance derived from the GEX profile."""
    if not profile.get("available"):
        return {"available": False, "reason": profile.get("reason")}

    regime = profile["regime"]
    flip = profile.get("flip_level")
    warnings = []
    strike_guidance = []

    if regime == "negative_gamma":
        warnings.append(
            "Negative gamma regime — dealer hedging AMPLIFIES moves. The range-bound "
            "assumption behind selling 0DTE credit is not supported today."
        )
    if flip is not None:
        side = "above" if spot >= flip else "below"
        if side == "below":
            warnings.append(
                f"Spot {spot:,.2f} is BELOW the gamma flip ({flip:,.2f}) — in the "
                "amplifying regime. Crossing back above it would restore the "
                "vol-suppressing one."
            )

    call_wall, put_wall = profile.get("call_wall"), profile.get("put_wall")
    if spread_type in ("bear_call", "iron_condor") and call_wall:
        strike_guidance.append(
            f"Bear call: put the short strike AT or ABOVE the call wall ({call_wall:,.0f}) "
            "— dealer hedging structurally defends it, so it works as a barrier."
        )
    if spread_type in ("bull_put", "iron_condor") and put_wall:
        strike_guidance.append(
            f"Bull put: put the short strike AT or BELOW the put wall ({put_wall:,.0f}) "
            "— the level dealer hedging tends to defend on the downside."
        )

    return {
        "available": True,
        "regime": regime,
        "net_gex_bn": profile["net_gex_bn"],
        "flip_level": flip,
        "spot_vs_flip": (None if flip is None else ("above" if spot >= flip else "below")),
        "call_wall": call_wall,
        "put_wall": put_wall,
        "note": _REGIME_NOTE[regime],
        "strike_guidance": strike_guidance,
        "warnings": warnings,
    }


def apply_gex_gate(timing: dict, guidance: dict) -> dict:
    """Downgrade the timing entry_quality one notch in a negative-gamma regime.

    The clock-based windows only know the time of day; the regime knows whether
    today's hedging flow damps moves or feeds them. A negative-gamma tape makes even
    a 'best' clock window a worse place to sell premium, so the gate lowers it and
    says why. Mutates and returns `timing`.
    """
    if not guidance.get("available") or guidance["regime"] != "negative_gamma":
        return timing
    before = timing.get("entry_quality")
    timing["entry_quality"] = _DOWNGRADE.get(before, before)
    timing["gex_gate"] = {
        "applied": True,
        "entry_quality_before": before,
        "reason": "Negative net GEX — dealer hedging amplifies moves; short premium is riskier "
        "than the clock alone suggests.",
    }
    return timing


def annotate_candidate(candidate: dict, profile: dict, spread_type: str) -> dict:
    """Tag a ranked candidate with where its short strike(s) sit versus the walls.

    'beyond_wall' = selling outside the gamma concentration (the wall stands between
    spot and your short strike — the position it is meant to be in). 'inside_wall' =
    the short strike is nearer to spot than the wall, so price can reach it without
    ever contesting the level dealers defend.
    """
    if not profile.get("available"):
        return candidate

    shorts = [leg for leg in candidate.get("legs", []) if leg.get("action", "").upper() == "SELL"]
    walls = {"C": profile.get("call_wall"), "P": profile.get("put_wall")}
    tags = {}
    for leg in shorts:
        wall = walls.get(leg["right"])
        if not wall:
            continue
        strike = leg["strike"]
        if strike == wall:
            placement = "at_wall"
        elif (leg["right"] == "C" and strike > wall) or (leg["right"] == "P" and strike < wall):
            placement = "beyond_wall"
        else:
            placement = "inside_wall"
        tags["call" if leg["right"] == "C" else "put"] = {
            "wall": wall,
            "short_strike": strike,
            "placement": placement,
            "distance_to_wall": round(abs(strike - wall), 2),
        }

    if tags:
        candidate["gex"] = tags
        candidate["gex_ok"] = all(t["placement"] != "inside_wall" for t in tags.values())
    return candidate

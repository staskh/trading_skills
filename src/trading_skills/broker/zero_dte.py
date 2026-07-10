# ABOUTME: 0DTE credit-spread finder + executor using Interactive Brokers data.
# ABOUTME: Ranks bear-call/bull-put/iron-condor candidates by POP-weighted EV; places BAG combos.

import asyncio
import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from ib_async import IB, ComboLeg, Contract, Index, Option, Order, Stock
from scipy.stats import norm

from trading_skills.black_scholes import black_scholes_delta, implied_volatility
from trading_skills.broker.connection import CLIENT_IDS, ib_connection
from trading_skills.broker.zero_dte_stop import (
    emergency_close,
    place_spread_bracket,
    resolve_stop_cfg,
    stop_plan,
)
from trading_skills.economic_calendar import fetch_us_economic_events
from trading_skills.utils import fetch_with_timeout

NY = ZoneInfo("America/New_York")

# Cash-settled index underlyings need an Index() contract on their home exchange,
# not a Stock(). Everything else resolves as a SMART-routed equity/ETF.
INDEX_SPECS = {
    "SPX": "CBOE",
    "SPXW": "CBOE",
    "XSP": "CBOE",
    "NDX": "NASDAQ",
    "RUT": "CBOE",
    "RUTW": "CBOE",
    "VIX": "CBOE",
    "DJX": "CBOE",
}

DEFAULT_RATE = 0.045  # annualized risk-free rate for BS fallback

SPREAD_TYPES = ("bear_call", "bull_put", "iron_condor")

# Default cap on the short-leg |delta| at ENTRY, by underlying class. Indexes sell
# only well-OTM short legs (high POP); stocks allow a bit closer. "_index"/"_stock"
# are the class fallbacks; per-symbol keys may be added for tuning. Explicit --delta
# always wins.
ENTRY_MAX_DELTA = {
    "_index": 0.20,
    "_stock": 0.20,
}


def resolve_underlying(symbol: str):
    """Return (contract, sec_type, asset_type) for an equity or cash-settled index."""
    symbol = symbol.upper()
    if symbol in INDEX_SPECS:
        return Index(symbol, INDEX_SPECS[symbol], "USD"), "IND", "index"
    return Stock(symbol, "SMART", "USD"), "STK", "stock"


def resolve_entry_delta(symbol: str, asset_type: str, explicit: float | None) -> float | None:
    """Effective short-leg delta cap for entry: explicit --delta wins, else the preset.

    Indexes default to 0.10, stocks/ETFs to 0.20 (per-symbol keys override the class
    fallback in ENTRY_MAX_DELTA).
    """
    if explicit is not None:
        return explicit
    fallback = "_index" if asset_type == "index" else "_stock"
    return ENTRY_MAX_DELTA.get(symbol.upper(), ENTRY_MAX_DELTA[fallback])


def _today_ny() -> str:
    """Today's date in IB expiry format (YYYYMMDD), New York calendar."""
    return datetime.now(NY).strftime("%Y%m%d")


def _time_to_expiry_years(expiry: str) -> float:
    """Years from now until 16:00 ET on the expiry date (floored to ~1 minute)."""
    try:
        exp_date = datetime.strptime(expiry, "%Y%m%d").replace(hour=16, minute=0, tzinfo=NY)
    except ValueError:
        return 1.0 / (365 * 24 * 60)
    now = datetime.now(NY)
    seconds = (exp_date - now).total_seconds()
    seconds = max(seconds, 60.0)  # avoid T=0 blowing up the BS fallback
    return seconds / (365 * 24 * 60 * 60)


# --------------------------------------------------------------------------- #
# Intraday timing & event-risk guidance (deterministic, from the ET clock)
# --------------------------------------------------------------------------- #
def _mins(h: int, m: int) -> int:
    return h * 60 + m


def market_session(now: datetime) -> dict | None:
    """Return {is_trading_day, close_hm} for `now`'s date via the NYSE calendar.

    Handles holidays and early closes (half-days close 13:00 ET). Returns None if
    the calendar can't be consulted, so the caller falls back to a weekday guess.
    """
    try:
        import pandas_market_calendars as mcal

        d = now.strftime("%Y-%m-%d")
        sched = mcal.get_calendar("NYSE").schedule(start_date=d, end_date=d)
        if sched.empty:
            return {"is_trading_day": False, "close_hm": _mins(16, 0)}
        close_et = sched.iloc[0]["market_close"].tz_convert(NY)
        return {"is_trading_day": True, "close_hm": close_et.hour * 60 + close_et.minute}
    except Exception:
        return None


def assess_timing(now: datetime, spread_type: str, session: dict | None = None) -> dict:
    """Rate the current ET time as a 0DTE entry window for `spread_type`.

    Windows reflect intraday structure: the open is wide/whippy, mid-morning is
    the prime credit-spread window, midday suits iron condors, and the final hour
    is peak-gamma (dangerous to open new short premium).

    session (from market_session) supplies holiday / early-close awareness; without
    it, a plain weekday + 16:00 close is assumed.
    """
    hm = now.hour * 60 + now.minute
    if session is not None:
        trading_day = session["is_trading_day"]
        close_hm = session["close_hm"]
    else:
        trading_day = now.weekday() < 5
        close_hm = _mins(16, 0)

    def out(window, market_open, quality, rec):
        return {
            "window": window,
            "market_open": market_open,
            "entry_quality": quality,
            "recommendation": rec,
        }

    if not trading_day:
        reason = "weekend" if now.weekday() >= 5 else "market holiday"
        return out(
            "closed",
            False,
            "closed",
            f"US markets are closed ({reason}); 0DTE resumes the next session.",
        )
    if hm < _mins(9, 30):
        return out(
            "pre_market",
            False,
            "closed",
            "Pre-market — wait for the 9:30 ET open; option liquidity is poor now.",
        )
    if hm >= close_hm:
        return out(
            "after_hours",
            False,
            "closed",
            "After the close; today's 0DTE has settled — trade the next session.",
        )
    # Power hour and opening are checked before the fixed midday boundaries so an
    # early close (half-day) correctly compresses the afternoon.
    if hm >= close_hm - 60:
        return out(
            "power_hour",
            True,
            "avoid",
            "Final hour: peak gamma — high risk to open new short premium. Better to manage/close.",
        )

    is_condor = spread_type == "iron_condor"
    if hm < _mins(9, 45):
        return out(
            "opening_bell",
            True,
            "avoid",
            "First 15 min: widest spreads, whipsaw. Wait until ~9:45 to sell premium.",
        )
    if hm < _mins(11, 30):
        rec = (
            "Good liquidity, but condors do better after the range settles (midday lull)."
            if is_condor
            else "Prime window for credit spreads: tight spreads, clear trend, full-day theta."
        )
        return out("morning_prime", True, "good" if is_condor else "best", rec)
    if hm < _mins(14, 0):
        rec = (
            "Midday lull — ideal for iron condors: low vol and range-bound drift decay both wings."
            if is_condor
            else "Midday lull: thinner premium, choppier direction; smaller edge than AM."
        )
        return out("midday", True, "best" if is_condor else "fair", rec)
    return out(
        "afternoon",
        True,
        "fair",
        "Early afternoon: gamma rising — widen the short strike (--delta) and size down.",
    )


def _minutes_from_et(time_et: str | None) -> int | None:
    """Parse an 'HH:MM ET' string to minutes past midnight, or None."""
    if not time_et:
        return None
    hh, _, rest = time_et.partition(":")
    mm = rest[:2]
    if hh.strip().isdigit() and mm.isdigit():
        return int(hh) * 60 + int(mm)
    return None


def event_guidance(now: datetime, asset_type: str, live_events: list[dict] | None = None) -> dict:
    """Event-risk guidance for the day.

    With `live_events` (from fetch_us_economic_events) it reports the real scheduled
    releases — flagging high-impact ones and anything imminent. Without it, falls
    back to the recurring intraday windows plus a verify-before-trading checklist.
    """
    hm = now.hour * 60 + now.minute

    if live_events is not None:
        high = [e for e in live_events if e["impact"] == "high"]
        warnings = []
        for e in high:
            when = f" at {e['time_et']}" if e["time_et"] else ""
            warnings.append(f"{e['event']}{when} today — major vol risk for index 0DTE.")
        # Anything (any impact) landing within the next ~30 min is imminent.
        imminent = [
            e
            for e in live_events
            if (m := _minutes_from_et(e["time_et"])) is not None and hm <= m <= hm + 30
        ]
        for e in imminent:
            warnings.append(f"Imminent: {e['event']} at {e['time_et']} — hold off entering.")
        return {
            "source": "nasdaq",
            "near_release_window": bool(imminent),
            "high_impact_today": [e["event"] for e in high],
            "events_today": live_events,
            "warnings": warnings,
            "note": "Live US economic calendar (Nasdaq); times ET.",
        }

    # Fallback: recurring intraday windows + a reminder checklist.
    warnings = []
    if _mins(9, 55) <= hm <= _mins(10, 20):
        warnings.append("Near the 10:00 ET data window (ISM/JOLTS/sentiment) — expect a vol spike.")
    if _mins(13, 55) <= hm <= _mins(14, 30):
        warnings.append(
            "2:00 ET FOMC slot on meeting days — don't open new 0DTE into the announcement."
        )
    verify = [
        "FOMC rate decision — 2:00 ET on meeting days (whipsaws the afternoon)",
        "CPI / PPI / NFP / retail sales — 8:30 ET (gaps the open)",
        "ISM / JOLTS / consumer sentiment — 10:00 ET",
    ]
    if asset_type != "index":
        verify.append(
            "Underlying earnings — a report today/after close can gap through your strikes"
        )
    return {
        "source": "static",
        "near_release_window": bool(warnings),
        "warnings": warnings,
        "verify_before_trading": verify,
        "note": "Live calendar unavailable — verify today's economic calendar manually.",
    }


def build_timing(
    now: datetime,
    spread_type: str,
    asset_type: str,
    session: dict | None = None,
    live_events: list[dict] | None = None,
) -> dict:
    """Combined intraday-timing + event-risk guidance for the output."""
    timing = assess_timing(now, spread_type, session)
    timing["now_et"] = now.strftime("%H:%M ET")
    timing["events"] = event_guidance(now, asset_type, live_events)
    return timing


# --------------------------------------------------------------------------- #
# Probability of profit
# --------------------------------------------------------------------------- #
def pop_short(right: str, spot: float, strike: float, delta, iv, T: float, r: float):
    """Probability a short single-leg option expires worthless (spread's winning side).

    Primary: IBKR model delta (already reflects the vol skew), POP = 1 - |delta|.
    Fallback: Black-Scholes N(d2) from IBKR implied vol when delta is unavailable.
    Returns None when neither input is usable.
    """
    if delta is not None:
        return max(0.0, min(1.0, 1.0 - abs(delta)))

    if not (spot and strike and iv and iv > 0 and T and T > 0):
        return None

    d2 = (math.log(spot / strike) + (r - 0.5 * iv**2) * T) / (iv * math.sqrt(T))
    if right == "C":
        # short call wins if S_T < K; P(S_T > K) = N(d2)
        return max(0.0, min(1.0, 1.0 - norm.cdf(d2)))
    else:
        # short put wins if S_T > K; P(S_T < K) = N(-d2)
        return max(0.0, min(1.0, 1.0 - norm.cdf(-d2)))


def abs_short_delta(right: str, spot: float, strike: float, delta, iv, T: float, r: float):
    """|delta| of a short leg — IBKR delta if present, else Black-Scholes from IV.

    Used both to report the short-leg risk and to enforce the --delta cap.
    Returns None when neither a delta nor an IV is available.
    """
    if delta is not None:
        return abs(delta)
    if iv and iv > 0 and spot and T and T > 0:
        option_type = "call" if right == "C" else "put"
        return abs(black_scholes_delta(spot, strike, T, r, iv, option_type))
    return None


# --------------------------------------------------------------------------- #
# Pure spread construction / scoring
# --------------------------------------------------------------------------- #
def _leg_view(opt: dict) -> dict:
    """Trim an option quote to the fields we surface per leg."""
    return {
        "right": opt["right"],
        "strike": opt["strike"],
        "bid": opt.get("bid"),
        "ask": opt.get("ask"),
        "mid": round(opt["mid"], 2),
        "delta": round(opt["delta"], 4) if opt.get("delta") is not None else None,
        "iv": round(opt["iv"] * 100, 2) if opt.get("iv") is not None else None,
    }


def _tradeable(opt: dict) -> bool:
    """A leg is usable only if it has a positive mid we can price against."""
    return opt.get("mid") is not None and opt["mid"] > 0


def build_verticals(
    options: list[dict],
    right: str,
    spot: float,
    budget: float,
    T: float,
    r: float,
    *,
    min_pop: float = 0.0,
    max_width: float | None = None,
    max_short_delta: float | None = None,
    max_legs_out: int = 12,
) -> list[dict]:
    """Build all viable credit verticals for one option side.

    right="C" -> bear call spreads (short OTM call, long higher call).
    right="P" -> bull put spreads (short OTM put, long lower put).
    max_short_delta caps the |delta| of the short leg (a manual risk limit).
    """
    usable = sorted((o for o in options if _tradeable(o)), key=lambda o: o["strike"])
    strategy = "bear_call" if right == "C" else "bull_put"
    candidates = []

    for i, short in enumerate(usable):
        # Sell OTM: call above spot, put below spot.
        if right == "C" and short["strike"] < spot:
            continue
        if right == "P" and short["strike"] > spot:
            continue

        short_delta = abs_short_delta(
            right, spot, short["strike"], short.get("delta"), short.get("iv"), T, r
        )
        # Risk cap: skip if the short delta exceeds the limit (or can't be determined).
        if max_short_delta is not None and (short_delta is None or short_delta > max_short_delta):
            continue

        pop = pop_short(right, spot, short["strike"], short.get("delta"), short.get("iv"), T, r)
        if pop is None or pop < min_pop:
            continue

        # Cushion between spot and the strike we're selling (positive = OTM buffer).
        distance = short["strike"] - spot if right == "C" else spot - short["strike"]

        # Long leg is the protective wing, further OTM.
        if right == "C":
            longs = usable[i + 1 : i + 1 + max_legs_out]
        else:
            longs = list(reversed(usable[max(0, i - max_legs_out) : i]))

        for long_leg in longs:
            width = abs(long_leg["strike"] - short["strike"])
            if width <= 0 or (max_width is not None and width > max_width):
                continue

            net_credit = short["mid"] - long_leg["mid"]
            if net_credit <= 0 or net_credit >= width:
                continue  # no edge, or bad/crossed quotes

            max_profit_pc = net_credit * 100
            max_loss_pc = (width - net_credit) * 100
            if max_loss_pc <= 0:
                continue

            contracts = int(budget // max_loss_pc)
            if contracts < 1:
                continue  # cheapest single spread already exceeds the budget

            ev_pc = pop * max_profit_pc - (1 - pop) * max_loss_pc
            if right == "C":
                breakeven = short["strike"] + net_credit
            else:
                breakeven = short["strike"] - net_credit

            candidates.append(
                {
                    "strategy": strategy,
                    "legs": [
                        {"action": "sell", **_leg_view(short)},
                        {"action": "buy", **_leg_view(long_leg)},
                    ],
                    "width": round(width, 2),
                    "net_credit": round(net_credit, 2),
                    "pop": round(pop, 4),
                    "short_delta": round(short_delta, 4) if short_delta is not None else None,
                    "distance_to_short": round(distance, 2),
                    "distance_to_short_pct": round(distance / spot * 100, 2),
                    "contracts": contracts,
                    "max_profit_per_contract": round(max_profit_pc, 2),
                    "max_loss_per_contract": round(max_loss_pc, 2),
                    "credit_total": round(max_profit_pc * contracts, 2),
                    "max_profit_total": round(max_profit_pc * contracts, 2),
                    "max_loss_total": round(max_loss_pc * contracts, 2),
                    "capital_at_risk": round(max_loss_pc * contracts, 2),
                    "ev_per_contract": round(ev_pc, 2),
                    "ev_total": round(ev_pc * contracts, 2),
                    "breakeven": round(breakeven, 2),
                    "risk_reward": round(max_profit_pc / max_loss_pc, 3),
                }
            )

    return candidates


def build_iron_condors(
    calls: list[dict],
    puts: list[dict],
    spot: float,
    budget: float,
    T: float,
    r: float,
    *,
    min_pop: float = 0.0,
    max_width: float | None = None,
    max_short_delta: float | None = None,
    max_legs_out: int = 12,
    top_per_side: int = 10,
) -> list[dict]:
    """Combine the strongest bear-call and bull-put verticals into iron condors.

    Sizing is by the condor's true max loss (only one wing can be breached at
    expiration): max_loss = max(call_width, put_width) - combined_credit.
    max_short_delta caps the |delta| of BOTH short legs (a manual risk limit).
    """
    # Size single-side verticals against the full budget first; the pairing below
    # re-sizes contracts against the combined condor risk. The delta cap flows into
    # each side here, so both short legs of the condor respect it.
    call_side = build_verticals(
        calls,
        "C",
        spot,
        budget,
        T,
        r,
        min_pop=0.0,
        max_width=max_width,
        max_short_delta=max_short_delta,
        max_legs_out=max_legs_out,
    )
    put_side = build_verticals(
        puts,
        "P",
        spot,
        budget,
        T,
        r,
        min_pop=0.0,
        max_width=max_width,
        max_short_delta=max_short_delta,
        max_legs_out=max_legs_out,
    )
    if not call_side or not put_side:
        return []

    call_side = sorted(call_side, key=lambda c: c["ev_per_contract"], reverse=True)[:top_per_side]
    put_side = sorted(put_side, key=lambda c: c["ev_per_contract"], reverse=True)[:top_per_side]

    condors = []
    for call in call_side:
        short_call = call["legs"][0]["strike"]
        call_credit = call["net_credit"]
        call_pop = call["pop"]
        for put in put_side:
            short_put = put["legs"][0]["strike"]
            if short_put >= short_call:
                continue  # short strikes must bracket spot, not cross

            put_credit = put["net_credit"]
            combined_credit = call_credit + put_credit
            width = max(call["width"], put["width"])
            max_loss = width - combined_credit
            if max_loss <= 0:
                continue

            max_profit_pc = combined_credit * 100
            max_loss_pc = max_loss * 100
            contracts = int(budget // max_loss_pc)
            if contracts < 1:
                continue

            # Price stays between the short strikes: POP = call_pop + put_pop - 1.
            pop = call_pop + put["pop"] - 1.0
            pop = max(0.0, min(1.0, pop))
            if pop < min_pop:
                continue

            ev_pc = pop * max_profit_pc - (1 - pop) * max_loss_pc
            condors.append(
                {
                    "strategy": "iron_condor",
                    "legs": [put["legs"][0], put["legs"][1], call["legs"][0], call["legs"][1]],
                    "put_width": put["width"],
                    "call_width": call["width"],
                    "net_credit": round(combined_credit, 2),
                    "pop": round(pop, 4),
                    "short_call_delta": call["short_delta"],
                    "short_put_delta": put["short_delta"],
                    "call_distance_to_short": call["distance_to_short"],
                    "put_distance_to_short": put["distance_to_short"],
                    "contracts": contracts,
                    "max_profit_per_contract": round(max_profit_pc, 2),
                    "max_loss_per_contract": round(max_loss_pc, 2),
                    "credit_total": round(max_profit_pc * contracts, 2),
                    "max_profit_total": round(max_profit_pc * contracts, 2),
                    "max_loss_total": round(max_loss_pc * contracts, 2),
                    "capital_at_risk": round(max_loss_pc * contracts, 2),
                    "ev_per_contract": round(ev_pc, 2),
                    "ev_total": round(ev_pc * contracts, 2),
                    "breakeven_low": round(short_put - combined_credit, 2),
                    "breakeven_high": round(short_call + combined_credit, 2),
                    "profit_range": f"{short_put} - {short_call}",
                    "risk_reward": round(max_profit_pc / max_loss_pc, 3),
                }
            )

    return condors


def rank_candidates(candidates: list[dict], top: int) -> list[dict]:
    """Rank by total POP-weighted expected value, breaking ties toward higher POP."""
    ranked = sorted(candidates, key=lambda c: (c["ev_total"], c["pop"]), reverse=True)
    return ranked[:top]


# --------------------------------------------------------------------------- #
# IB data access
# --------------------------------------------------------------------------- #
def _select_chain(chains: list, target_expiry: str):
    """Pick the option chain (exchange/tradingClass) that carries the target expiry.

    Index dailies live on a weekly trading class (e.g. SPXW, RUTW), so we cannot
    blindly prefer the standard class; we require the target date to be present.
    """
    with_expiry = [c for c in chains if target_expiry in c.expirations]
    pool = with_expiry or chains
    smart = [c for c in pool if c.exchange == "SMART"]
    ranked = smart or pool
    return max(ranked, key=lambda c: len(c.strikes))


async def _underlying_price(ib: IB, contract) -> float | None:
    [ticker] = await ib.reqTickersAsync(contract)
    await asyncio.sleep(0.5)
    price = ticker.marketPrice()
    if price is None or math.isnan(price):
        price = ticker.close if ticker.close and not math.isnan(ticker.close) else None
    return price


def _resolve_quote(bid, ask, last, close, g_delta, g_iv, spot, strike, right, T, r, allow_stale):
    """Resolve one option's (mid, delta, iv, stale, no_live_quote) from raw ticks.

    Pricing and greeks come from IBKR (bid/ask/last + model greeks). Only when
    allow_stale is True does it fall back to the prior settlement `close` for the
    mid and derive IV by inverting Black-Scholes on it — otherwise a leg with no
    live quote/greeks is left un-priceable (mid=None) and dropped downstream.
    """
    no_live = bid is None and ask is None and last is None

    mid = None
    stale = False
    if bid is not None and ask is not None:
        mid = (bid + ask) / 2
    elif last is not None:
        mid = last
    elif allow_stale and close is not None:
        mid = close  # off-hours: prior settlement is the only mark available
        stale = True

    delta = g_delta
    iv = g_iv
    # Compute IV only under --allow-stale; by default greeks come solely from IBKR.
    if iv is None and allow_stale and mid is not None and spot:
        option_type = "call" if right == "C" else "put"
        iv = implied_volatility(mid, spot, strike, T, r, option_type)

    return mid, delta, iv, stale, no_live


async def _fetch_side(
    ib: IB,
    symbol: str,
    expiry: str,
    strikes: list[float],
    right: str,
    exchange: str,
    trading_class: str,
    spot: float,
    T: float,
    r: float,
    allow_stale: bool,
) -> list[dict]:
    """Qualify and quote one option side, capturing delta and IV from model greeks.

    With allow_stale=True, legs lacking live quotes/greeks (outside RTH) fall back
    to the prior settlement close + Black-Scholes IV, marked stale. By default such
    legs are left un-priceable and dropped.
    """
    contracts = [
        Option(symbol, expiry, strike, right, exchange, tradingClass=trading_class, currency="USD")
        for strike in strikes
    ]

    ib_logger = logging.getLogger("ib_async")
    prev_level = ib_logger.level
    ib_logger.setLevel(logging.CRITICAL)  # silence warnings for non-existent strikes
    try:
        try:
            qualified = await asyncio.wait_for(ib.qualifyContractsAsync(*contracts), timeout=20)
        except asyncio.TimeoutError:
            return []
        qualified = [c for c in qualified if c is not None and c.conId]
        if not qualified:
            return []
        try:
            tickers = await asyncio.wait_for(ib.reqTickersAsync(*qualified), timeout=30)
        except asyncio.TimeoutError:
            return []
    finally:
        ib_logger.setLevel(prev_level)

    await asyncio.sleep(1)  # let streamed greeks/quotes arrive

    results = []
    for t in tickers:
        if t.contract is None:
            continue
        bid = t.bid if t.bid and t.bid > 0 else None
        ask = t.ask if t.ask and t.ask > 0 else None
        last = t.last if t.last and t.last > 0 else None
        close = t.close if t.close and not math.isnan(t.close) and t.close > 0 else None

        g_delta = g_iv = None
        if t.modelGreeks:
            if t.modelGreeks.delta is not None and not math.isnan(t.modelGreeks.delta):
                g_delta = t.modelGreeks.delta
            if t.modelGreeks.impliedVol and not math.isnan(t.modelGreeks.impliedVol):
                g_iv = t.modelGreeks.impliedVol

        mid, delta, iv, stale, no_live = _resolve_quote(
            bid, ask, last, close, g_delta, g_iv, spot, t.contract.strike, right, T, r, allow_stale
        )

        results.append(
            {
                "strike": t.contract.strike,
                "right": right,
                "bid": round(bid, 2) if bid is not None else None,
                "ask": round(ask, 2) if ask is not None else None,
                "close": round(close, 2) if close is not None else None,
                "mid": mid,
                "delta": delta,
                "iv": iv,
                "stale": stale,
                "no_live_quote": no_live,
            }
        )

    return sorted(results, key=lambda x: x["strike"])


async def get_0dte_expiries(symbol: str, port: int = 7496) -> dict:
    """List near-term expiries for a symbol, flagging whether a 0DTE exists today."""
    contract, sec_type, asset_type = resolve_underlying(symbol)
    try:
        async with ib_connection(port, CLIENT_IDS["zero_dte"]) as ib:
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified or qualified[0] is None or not qualified[0].conId:
                return {"success": False, "error": f"Unknown symbol: {symbol}"}

            chains = await ib.reqSecDefOptParamsAsync(symbol.upper(), "", sec_type, contract.conId)
            if not chains:
                return {"success": False, "error": f"No options found for {symbol}"}

            expiries = sorted({e for c in chains for e in c.expirations})
            today = _today_ny()
            return {
                "success": True,
                "symbol": symbol.upper(),
                "asset_type": asset_type,
                "source": "ibkr",
                "today": today,
                "has_0dte": today in expiries,
                "expiries": expiries,
            }
    except ConnectionError as e:
        return {"success": False, "error": str(e)}


# Order statuses that still hold size in the market (a real duplicate).
_ACTIVE_STATUSES = {"PendingSubmit", "ApiPending", "PreSubmitted", "Submitted"}


async def _find_duplicate_order(ib: IB, order_ref: str, account: str):
    """Return an existing active Trade with the same orderRef + account, else None.

    Guards against a second --execute placing a duplicate spread for the same
    symbol/expiry/type (orderRef is ZDTE_<type>_<symbol>_<expiry>).
    """
    await fetch_with_timeout(ib.reqAllOpenOrdersAsync(), timeout=5, default=[])
    for trade in ib.openTrades():
        o = trade.order
        if (getattr(o, "orderRef", "") or "") != order_ref:
            continue
        if account and (getattr(o, "account", "") or "") != account:
            continue
        if trade.orderStatus.status in _ACTIVE_STATUSES:
            return trade
    return None


async def _place_spread_order(
    ib: IB,
    candidate: dict,
    symbol: str,
    expiry: str,
    exchange: str,
    trading_class: str,
    account: str,
    limit_credit: float,
    order_ref: str,
) -> dict:
    """Place the spread as a single native BAG combo, limit at the net credit.

    Legs carry their as-traded actions (SELL short, BUY long), so the combo's
    natural price is negative (a credit). We BUY the combo at lmtPrice=-credit,
    which guarantees a fill only at or better than that credit. Works uniformly
    for 2-leg verticals and 4-leg iron condors.
    """
    legs_spec = candidate["legs"]
    contracts = [
        Option(
            symbol,
            expiry,
            leg["strike"],
            leg["right"],
            exchange,
            tradingClass=trading_class,
            currency="USD",
        )
        for leg in legs_spec
    ]
    qualified = await fetch_with_timeout(
        ib.qualifyContractsAsync(*contracts), timeout=15, default=[]
    )
    qualified = [q for q in qualified if q is not None and q.conId]
    if len(qualified) != len(legs_spec):
        return {"ok": False, "error": "Could not qualify all spread legs"}

    combo_legs = []
    for leg, qc in zip(legs_spec, qualified):
        cl = ComboLeg()
        cl.conId = qc.conId
        cl.ratio = 1
        cl.action = leg["action"].upper()  # SELL the short leg, BUY the long wing
        cl.exchange = exchange
        combo_legs.append(cl)

    combo = Contract()
    combo.symbol = symbol
    combo.secType = "BAG"
    combo.currency = "USD"
    combo.exchange = exchange
    combo.comboLegs = combo_legs

    order = Order()
    order.action = "BUY"  # execute legs exactly as defined
    order.orderType = "LMT"
    order.totalQuantity = candidate["contracts"]
    order.lmtPrice = round(-abs(limit_credit), 2)  # negative price = net credit received
    order.tif = "DAY"  # 0DTE — no point resting past today's close
    order.orderRef = order_ref
    order.account = account  # route execution to the chosen account

    trade = ib.placeOrder(combo, order)
    await asyncio.sleep(2)  # let IB acknowledge and report initial status

    st = trade.orderStatus
    return {
        "ok": True,
        "order_id": trade.order.orderId,
        "order_ref": order_ref,
        "account": account,
        "status": st.status,
        "filled": st.filled,
        "remaining": st.remaining,
        "quantity": order.totalQuantity,
        "limit_price": order.lmtPrice,
        "limit_is_net_credit": round(abs(limit_credit), 2),
    }


async def find_0dte_spreads(
    symbol: str,
    spread_type: str = "bear_call",
    budget: float = 1000.0,
    expiry: str | None = None,
    port: int = 7496,
    *,
    account: str | None = None,
    execute: bool = False,
    pick: int = 1,
    limit: float | None = None,
    replace: bool = False,
    top: int = 5,
    min_pop: float = 0.0,
    max_width: float | None = None,
    max_short_delta: float | None = None,
    allow_stale: bool = False,
    fetch_events: bool = True,
    stop_mult: float | None = None,
    stop_buffer: float | None = None,
    stop_delta: float | None = None,
    profit_target: float | None = None,
    time_exit: str | None = None,
    fill_timeout: float = 20.0,
    rate: float = DEFAULT_RATE,
    strike_band: float = 0.15,
) -> dict:
    """Find the best 0DTE credit spreads of `spread_type` within `budget`.

    account: the IBKR account the trade is committed to. Validated against the
        connection's managed accounts and recorded on the result.
    max_short_delta: cap the |delta| of the short leg(s) — a manual risk limit.
    allow_stale: when True, price legs from the prior settlement close and derive
        greeks via Black-Scholes if IBKR streams no live quotes/greeks (off-hours).
        Default False: greeks come only from IBKR, so a closed market yields no
        candidates rather than stale, model-computed ones.
    execute: when True, place the chosen candidate as a live BAG combo order
        (default False = dry run, propose only). Requires a resolved account.
    pick: 1-based index into the ranked candidates to execute (default: the best).
    limit: net credit limit price override; defaults to the candidate's net credit.
    replace: when a live order with the same ref already rests, cancel and re-place
        it instead of refusing (the default is to refuse — the duplicate guard).
    """
    if spread_type not in SPREAD_TYPES:
        return {"success": False, "error": f"Unknown spread type: {spread_type}"}

    contract, sec_type, asset_type = resolve_underlying(symbol)
    symbol_u = symbol.upper()

    try:
        # Order placement needs a writable connection; analysis stays read-only.
        async with ib_connection(port, CLIENT_IDS["zero_dte"], readonly=not execute) as ib:
            ib.reqMarketDataType(4)  # delayed-frozen fallback outside RTH

            managed = ib.managedAccounts()
            if account and managed and account not in managed:
                return {
                    "success": False,
                    "error": f"Account {account} not found. Available: {managed}",
                    "symbol": symbol_u,
                }
            # Single-account logins have exactly one; pin the trade to it by default.
            trade_account = account or (managed[0] if len(managed) == 1 else None)

            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified or qualified[0] is None or not qualified[0].conId:
                return {"success": False, "error": f"Unknown symbol: {symbol}"}

            spot = await _underlying_price(ib, contract)
            if not spot or spot <= 0:
                return {"success": False, "error": f"Could not determine price for {symbol}"}

            chains = await ib.reqSecDefOptParamsAsync(symbol_u, "", sec_type, contract.conId)
            if not chains:
                return {"success": False, "error": f"No options found for {symbol}"}

            target = expiry or _today_ny()
            all_expiries = sorted({e for c in chains for e in c.expirations})
            if target not in all_expiries:
                nearest = [e for e in all_expiries if e >= target][:5] or all_expiries[:5]
                return {
                    "success": False,
                    "error": f"No expiry {target} for {symbol}. Nearest: {nearest}",
                    "symbol": symbol_u,
                    "asset_type": asset_type,
                }

            chain = _select_chain(chains, target)
            exchange = chain.exchange
            trading_class = chain.tradingClass

            lo, hi = spot * (1 - strike_band), spot * (1 + strike_band)
            strikes = sorted(s for s in chain.strikes if lo <= s <= hi)
            if not strikes:
                return {"success": False, "error": f"No strikes near spot for {symbol}"}

            need_calls = spread_type in ("bear_call", "iron_condor")
            need_puts = spread_type in ("bull_put", "iron_condor")

            T = _time_to_expiry_years(target)

            calls, puts = [], []
            tasks = []
            if need_calls:
                tasks.append(
                    _fetch_side(
                        ib,
                        symbol_u,
                        target,
                        strikes,
                        "C",
                        exchange,
                        trading_class,
                        spot,
                        T,
                        rate,
                        allow_stale,
                    )
                )
            if need_puts:
                tasks.append(
                    _fetch_side(
                        ib,
                        symbol_u,
                        target,
                        strikes,
                        "P",
                        exchange,
                        trading_class,
                        spot,
                        T,
                        rate,
                        allow_stale,
                    )
                )
            fetched = await asyncio.gather(*tasks)
            if need_calls:
                calls = fetched.pop(0)
            if need_puts:
                puts = fetched.pop(0)

            fetched_legs = calls + puts
            stale = any(o.get("stale") for o in fetched_legs)
            data_delay = "stalled - using yesterday's close" if stale else "real-time"
            # No live quotes and we didn't allow stale marks → market is likely closed.
            no_live_data = bool(fetched_legs) and all(o.get("no_live_quote") for o in fetched_legs)

            # Entry short-delta cap: explicit --delta wins, else per-class preset.
            eff_max_delta = resolve_entry_delta(symbol_u, asset_type, max_short_delta)

            if spread_type == "bear_call":
                candidates = build_verticals(
                    calls,
                    "C",
                    spot,
                    budget,
                    T,
                    rate,
                    min_pop=min_pop,
                    max_width=max_width,
                    max_short_delta=eff_max_delta,
                )
            elif spread_type == "bull_put":
                candidates = build_verticals(
                    puts,
                    "P",
                    spot,
                    budget,
                    T,
                    rate,
                    min_pop=min_pop,
                    max_width=max_width,
                    max_short_delta=eff_max_delta,
                )
            else:
                candidates = build_iron_condors(
                    calls,
                    puts,
                    spot,
                    budget,
                    T,
                    rate,
                    min_pop=min_pop,
                    max_width=max_width,
                    max_short_delta=eff_max_delta,
                )

            ranked = rank_candidates(candidates, top)

            # --- Timing & event guidance (fetch the live calendar off-thread) ---
            now_et = datetime.now(NY)
            session = market_session(now_et)
            live_events = None
            if fetch_events:
                cal_date = f"{target[:4]}-{target[4:6]}-{target[6:]}"
                live_events = await fetch_with_timeout(
                    asyncio.to_thread(fetch_us_economic_events, cal_date), timeout=12, default=None
                )
            timing = build_timing(now_et, spread_type, asset_type, session, live_events)

            # --- Execute (place the chosen candidate as a live combo) ---
            order_result = None
            if execute:
                order_result = await _maybe_execute(
                    ib,
                    ranked,
                    pick,
                    trade_account,
                    budget,
                    limit,
                    symbol_u,
                    target,
                    exchange,
                    trading_class,
                    spread_type,
                    replace=replace,
                    spot=spot,
                    T=T,
                    rate=rate,
                    underlying_conid=contract.conId,
                    underlying_exch=INDEX_SPECS.get(symbol_u, "SMART"),
                    stop_cfg=resolve_stop_cfg(
                        symbol_u,
                        stop_mult,
                        stop_buffer,
                        stop_delta,
                        fill_timeout,
                        target=profit_target,
                        time_exit=time_exit,
                    ),
                )

            return {
                "success": True,
                "symbol": symbol_u,
                "asset_type": asset_type,
                "source": "ibkr",
                "spread_type": spread_type,
                "account": trade_account,
                "dry_run": not execute,
                "data_delay": data_delay,
                "underlying_price": round(spot, 2),
                "expiry": target,
                "dte": 0 if target == _today_ny() else None,
                "budget": budget,
                "trading_class": trading_class,
                "max_short_delta": eff_max_delta,
                "candidates_evaluated": len(candidates),
                "timing": timing,
                "best": ranked[0] if ranked else None,
                "candidates": ranked,
                "picked": pick if execute else None,
                "order": order_result,
                "hint": (
                    "No live quotes from IBKR (market likely closed). Greeks are taken "
                    "only from IBKR by default. Re-run with --allow-stale to price from "
                    "yesterday's close and derive greeks via Black-Scholes."
                    if (not candidates and not allow_stale and no_live_data)
                    else None
                ),
                "note": (
                    "POP from IBKR short-leg delta (BS N(d2) fallback). "
                    "Model-implied probabilities, not guarantees. "
                    "Sizing caps total max loss at budget."
                ),
            }
    except ConnectionError as e:
        return {"success": False, "error": str(e)}


async def _await_fill(ib, order_id: int, timeout: float) -> str:
    """Poll the order's status until Filled/terminal or timeout. Returns the status."""
    deadline = timeout
    status = "PendingSubmit"
    while deadline > 0:
        trade = next((t for t in ib.trades() if t.order.orderId == order_id), None)
        if trade is not None:
            status = trade.orderStatus.status
            if status in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
                return status
        await asyncio.sleep(1)
        deadline -= 1
    return status


async def _maybe_execute(
    ib,
    ranked,
    pick,
    trade_account,
    budget,
    limit,
    symbol_u,
    target,
    exchange,
    trading_class,
    spread_type,
    *,
    replace=False,
    spot,
    T,
    rate,
    underlying_conid,
    underlying_exch,
    stop_cfg,
):
    """Guard, place the entry, then atomically attach its stop.

    Flow: place entry → wait for fill → on fill place the protective stop; if the
    entry does not fill in time, cancel it (never hold an unprotected position); if
    the stop fails after a fill, emergency-market-close the spread.
    """
    if not ranked:
        return {"ok": False, "error": "No candidates to execute"}
    if pick < 1 or pick > len(ranked):
        return {"ok": False, "error": f"pick {pick} out of range (1-{len(ranked)})"}
    if not trade_account:
        return {
            "ok": False,
            "error": "Account required to execute; specify one (login manages multiple accounts)",
        }

    candidate = ranked[pick - 1]
    # Re-check the sized risk still fits the budget before committing real money.
    if candidate["max_loss_total"] > budget + 1e-6:
        return {"ok": False, "error": "Chosen spread's max loss exceeds budget"}

    order_ref = f"ZDTE_{spread_type}_{symbol_u}_{target}"

    # Duplicate guard: refuse (or replace) if a live order with this ref already rests.
    existing = await _find_duplicate_order(ib, order_ref, trade_account)
    if existing:
        if not replace:
            return {
                "ok": False,
                "error": (
                    f"Duplicate: an active {order_ref} order already rests "
                    f"(id={existing.order.orderId}, status={existing.orderStatus.status}). "
                    "Use --replace to cancel and re-place, or cancel it first."
                ),
                "existing_order_id": existing.order.orderId,
            }
        ib.cancelOrder(existing.order)
        await asyncio.sleep(2)  # let the cancel register before re-placing

    limit_credit = limit if limit is not None else candidate["net_credit"]
    result = await _place_spread_order(
        ib,
        candidate,
        symbol_u,
        target,
        exchange,
        trading_class,
        trade_account,
        limit_credit,
        order_ref,
    )
    if existing and result.get("ok"):
        result["replaced_order_id"] = existing.order.orderId
    if not result.get("ok"):
        return result

    # --- Atomic stop: never hold an unprotected position ---
    status = await _await_fill(ib, result["order_id"], stop_cfg["fill_timeout"])
    result["entry_status"] = status
    if status != "Filled":
        # No confirmed position — cancel the working entry so it can't fill unprotected.
        entry = next((t for t in ib.trades() if t.order.orderId == result["order_id"]), None)
        if entry is not None and status not in ("Cancelled", "ApiCancelled"):
            ib.cancelOrder(entry.order)
        result["ok"] = False
        result["bracket"] = {
            "ok": False,
            "error": f"Entry not filled ({status}) within {stop_cfg['fill_timeout']}s; "
            "cancelled to avoid an unprotected position. Use a marketable --limit or "
            "retry during liquid hours.",
        }
        return result

    plans = stop_plan(
        candidate,
        spot,
        T,
        rate,
        mult=stop_cfg["mult"],
        buffer_pts=stop_cfg["buffer"],
        target_delta=stop_cfg["delta"],
    )
    stop_ref = f"ZDTE_STOP_{spread_type}_{symbol_u}_{target}"
    cutoff = stop_cfg.get("time_exit")
    time_cutoff = f"{target} {cutoff}:00 US/Eastern" if cutoff else None
    bracket = await place_spread_bracket(
        ib,
        candidate,
        symbol_u,
        target,
        exchange,
        trading_class,
        underlying_conid,
        underlying_exch,
        trade_account,
        stop_ref,
        plans,
        credit=candidate["net_credit"],
        target_frac=stop_cfg["target"],
        time_cutoff=time_cutoff,
    )
    result["bracket"] = bracket
    if not bracket.get("ok"):
        # Protection failed on a live position — flatten immediately.
        result["emergency_close"] = await emergency_close(
            ib,
            candidate,
            symbol_u,
            target,
            exchange,
            trading_class,
            trade_account,
            f"ZDTE_EMERG_{symbol_u}_{target}",
        )
        result["ok"] = False
    return result

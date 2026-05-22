# ABOUTME: Analyzes PMCC (Poor Man's Covered Call / diagonal spread) positions from IB portfolio.
# ABOUTME: Advises on short leg risk, daily P&L projections, and roll recommendations.

import asyncio
import math
from collections import defaultdict
from datetime import datetime, timedelta

from scipy.optimize import minimize_scalar
from scipy.stats import norm

from trading_skills.black_scholes import (
    black_scholes_delta,
    black_scholes_price,
    estimate_iv,
    implied_volatility,
)
from trading_skills.broker.connection import (
    CLIENT_IDS,
    best_option_chain,
    fetch_positions,
    fetch_spot_prices,
    ib_connection,
    normalize_positions,
)
from trading_skills.utils import (
    _NY,
    days_to_expiry,
    fetch_with_timeout,
    generated_at_str,
    is_trading_now,
    safe_value,
    trading_sessions,
)

RISK_FREE_RATE = 0.045
NET_CREDIT_MIN = -0.10  # max debit allowed when rolling


# ===========================================================================
# ANALYTICS (no IBKR dependency — fully testable in isolation)
# ===========================================================================


def get_option_price(quote: dict, price_mode: str) -> float | None:
    """Extract option price from a quote dict using the configured price mode."""
    bid = quote.get("bid")
    ask = quote.get("ask")
    last = quote.get("last") or quote.get("lastPrice")

    if price_mode == "last":
        return last if last and last > 0 else None

    # mid (default)
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2
    if bid and bid > 0:
        return bid
    if ask and ask > 0:
        return ask
    return last if last and last > 0 else None


def calc_iv(price: float, spot: float, strike: float, dte_days: float, right: str) -> float | None:
    """Calculate implied volatility from option price via Newton-Raphson / bisection."""
    if not price or price <= 0:
        return None
    T = max(dte_days, 1 / 24) / 365
    opt_type = "call" if right == "C" else "put"
    return implied_volatility(price, spot, strike, T, RISK_FREE_RATE, opt_type)


def calc_delta(spot: float, strike: float, dte_days: float, iv: float, right: str) -> float:
    """Calculate Black-Scholes delta."""
    T = max(dte_days, 1 / 24) / 365
    opt_type = "call" if right == "C" else "put"
    return black_scholes_delta(spot, strike, T, RISK_FREE_RATE, iv, opt_type)


def calc_assignment_prob(
    spot: float, strike: float, dte_days: float, iv: float, right: str
) -> float:
    """Calculate probability of assignment (= probability of expiring ITM).

    Uses N(d2) for calls, N(-d2) for puts — the risk-neutral probability that
    the option expires in the money.
    """
    T = max(dte_days, 1 / 24) / 365
    if T <= 0 or iv <= 0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(spot / strike) + (RISK_FREE_RATE + 0.5 * iv**2) * T) / (iv * sqrt_T)
    d2 = d1 - iv * sqrt_T
    return norm.cdf(d2) if right == "C" else norm.cdf(-d2)


def calc_bs_price(spot: float, strike: float, dte_days: float, iv: float, right: str) -> float:
    """Calculate Black-Scholes option price."""
    T = max(dte_days, 0) / 365
    opt_type = "call" if right == "C" else "put"
    return black_scholes_price(spot, strike, T, RISK_FREE_RATE, iv, opt_type)


def find_optimal_exit_spot(
    long_strike: float,
    long_days_rem: int,
    long_iv: float,
    long_cost: float,
    short_strike: float,
    short_days_rem: int,
    short_iv: float,
    short_premium: float,
    spot: float,
    right: str = "C",
) -> tuple[float, float]:
    """Find the spot price that maximizes P&L if both legs are closed on a given day.

    For a diagonal call spread the P&L is unimodal in S: it rises as S approaches
    short_strike (long delta > short delta), then falls once the short's gamma drives
    its delta above the long's delta.  Returns (optimal_spot, pnl_per_share).
    """

    def neg_pnl(S: float) -> float:
        lp = calc_bs_price(S, long_strike, max(long_days_rem, 0), long_iv, right)
        sp = calc_bs_price(S, short_strike, max(short_days_rem, 0), short_iv, right)
        # short_premium excluded: already realised as income and misleading after rolls
        return -((lp - long_cost) - sp)

    lo = max(spot * 0.5, long_strike * 1.01)
    hi = spot * 2.0
    result = minimize_scalar(neg_pnl, bounds=(lo, hi), method="bounded")
    return round(result.x, 2), round(-result.fun, 4)


def calc_daily_pnl_table(
    long_strike: float,
    long_dte: float,
    long_cost: float,
    long_iv: float,
    short_strike: float,
    short_dte: float,
    short_premium: float,
    short_iv: float,
    qty: int,
    spot: float | None = None,
    right: str = "C",
    n_trading_days: int = 5,
) -> list[dict]:
    """P&L table for the next n_trading_days (capped at short expiry).

    Each row shows the spot that maximises exit P&L on that calendar date
    and the resulting P&L, scaled by qty * 100.
    """
    today = datetime.now(_NY).date()
    short_exp_date = today + timedelta(days=short_dte)

    future_days = trading_sessions(today, today + timedelta(days=30))[:n_trading_days]
    future_days = [d for d in future_days if d <= short_exp_date]
    if not future_days:
        future_days = [today]

    search_spot = spot if spot and spot > 0 else short_strike

    results = []
    for d in future_days:
        day_offset = (d - today).days
        short_days_rem = max(short_dte - day_offset, 0)
        long_days_rem = max(long_dte - day_offset, 1)

        opt_spot, pnl_per_share = find_optimal_exit_spot(
            long_strike=long_strike,
            long_days_rem=long_days_rem,
            long_iv=long_iv,
            long_cost=long_cost,
            short_strike=short_strike,
            short_days_rem=short_days_rem,
            short_iv=short_iv,
            short_premium=short_premium,
            spot=search_spot,
            right=right,
        )
        results.append(
            {
                "date": d.isoformat(),
                "days_to_short_expiry": short_days_rem,
                "optimal_spot": opt_spot,
                "pnl": round(pnl_per_share * qty * 100, 2),
            }
        )
    return results


def calc_profit_per_day(
    avg_cost: float,
    dte: float,
    current_price: float | None = None,
) -> float:
    """Original premium captured per remaining day.

    (avg_cost - current_price) / dte: profit already locked in relative to
    remaining time. Negative when the short is underwater (current_price > avg_cost).
    Falls back to avg_cost / dte when current price is unavailable.
    """
    if current_price is not None and current_price >= 0:
        return (avg_cost - current_price) / max(dte, 1 / 24)
    return avg_cost / max(dte, 1 / 24)


def calc_pnl_if_assigned(
    long_strike: float,
    long_dte: float,
    long_cost: float,
    long_iv: float,
    short_strike: float,
    short_dte: float,
    total_premium: float,
    qty: int,
) -> float:
    """Total P&L (qty × 100 shares) if the short expires ITM at expiry.

    Assumes the long leg is sold at its BS value at the moment of assignment
    (spot = short_strike, remaining DTE = long_dte − short_dte), which is
    more accurate than using intrinsic spread width when the long has time value.
    """
    long_days_at_assignment = max(long_dte - short_dte, 0)
    long_price = calc_bs_price(short_strike, long_strike, long_days_at_assignment, long_iv, "C")
    return round((long_price - long_cost + total_premium) * 100 * qty, 2)


def check_earnings_warning(
    earnings_date: str | None,
    earnings_timing: str | None,
    short_expiry: str,
    roll_candidates: list[dict],
) -> dict:
    """Check if earnings fall in risky windows relative to the short leg or roll candidates.

    Warns on current short if earnings fall within the last 7 days before short expiry.
    Warns on roll candidates (1-based indices) if earnings fall between today and roll expiry.
    """
    if not earnings_date:
        return {"date": None, "timing": None, "warning_short": False, "warning_roll_indices": []}

    today = datetime.now(_NY).date()
    earn_dt = datetime.strptime(earnings_date, "%Y-%m-%d").date()
    short_exp_dt = datetime.strptime(short_expiry, "%Y%m%d").date()

    in_window = (short_exp_dt - timedelta(days=7)) <= earn_dt <= short_exp_dt
    warning_short = today <= earn_dt and in_window

    warning_roll_indices = []
    for i, roll in enumerate(roll_candidates, 1):
        roll_exp_dt = datetime.strptime(roll["expiry"], "%Y%m%d").date()
        if today <= earn_dt <= roll_exp_dt:
            warning_roll_indices.append(i)

    return {
        "date": earnings_date,
        "timing": earnings_timing,
        "warning_short": warning_short,
        "warning_roll_indices": warning_roll_indices,
    }


def score_roll_candidate(current_delta: float, candidate: dict) -> float:
    """Score a roll candidate. Higher = better.

    Weighs: delta reduction, net credit received, days of additional coverage.
    """
    delta_improvement = current_delta - candidate["delta"]
    net_credit = candidate.get("net_credit", 0)
    dte = candidate.get("dte", 0)
    return delta_improvement * 100 + net_credit * 10 + dte * 0.1


def find_best_rolls(
    current_short_strike: float,
    current_short_expiry: str,
    current_short_dte: float,
    current_short_price: float,
    current_delta: float,
    roll_chains: dict,
    spot: float,
    long_strike: float,
    long_cost: float,
    long_dte: float,
    long_iv: float,
    qty: int,
    min_roll_dte: int,
    price_mode: str,
) -> list[dict]:
    """Find top-3 roll candidates satisfying both criteria:

    (a) delta < current short delta
    (b) net credit >= NET_CREDIT_MIN (not a large debit)

    Ranks by: delta reduction, net credit, DTE.
    """
    candidates = []

    for expiry, quotes in roll_chains.items():
        dte = days_to_expiry(expiry)
        if dte < min_roll_dte:
            continue
        if expiry == current_short_expiry:
            continue

        for quote in quotes:
            price = get_option_price(quote, price_mode)
            if not price or price <= 0:
                continue

            strike = quote["strike"]
            iv = calc_iv(price, spot, strike, dte, "C")
            if not iv:
                iv = estimate_iv(spot, strike, max(dte, 1 / 24) / 365, "call")
            if not iv:
                continue

            delta = abs(calc_delta(spot, strike, dte, iv, "C"))
            prob = calc_assignment_prob(spot, strike, dte, iv, "C")

            if delta >= current_delta:
                continue

            net_credit = price - current_short_price
            if net_credit < NET_CREDIT_MIN:
                continue

            profit_per_day = net_credit / max(dte, 1 / 24)
            pnl_if_assigned = calc_pnl_if_assigned(
                long_strike, long_dte, long_cost, long_iv, strike, dte, price, qty
            )

            candidates.append(
                {
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "price": round(price, 2),
                    "delta": round(delta, 4),
                    "assignment_prob": round(prob * 100, 1),
                    "iv_pct": round(iv * 100, 1),
                    "net_credit": round(net_credit, 2),
                    "profit_per_day": round(profit_per_day, 4),
                    "pnl_if_assigned": round(pnl_if_assigned, 2),
                    "bid": quote.get("bid"),
                    "ask": quote.get("ask"),
                }
            )

    candidates.sort(key=lambda c: score_roll_candidate(current_delta, c), reverse=True)
    return candidates[:3]


def build_comparison_table(
    current: dict,
    rolls: list[dict],
    long_pos: dict,
    long_dte: float,
    long_iv: float,
    qty: int,
) -> dict:
    """Side-by-side comparison of current short and up to 3 roll candidates."""

    def _entry(pos: dict) -> dict:
        long_strike = long_pos["strike"]
        long_cost = long_pos.get("avg_cost", 0)
        short_strike = pos["strike"]
        short_dte = pos.get("dte") or 0
        total_premium = pos.get("total_premium") or pos.get("price", 0)

        pnl_if_assigned = None
        if long_strike and short_strike > long_strike:
            pnl_if_assigned = calc_pnl_if_assigned(
                long_strike,
                long_dte,
                long_cost,
                long_iv,
                short_strike,
                short_dte,
                total_premium,
                qty,
            )

        return {
            "strike": short_strike,
            "expiry": pos.get("expiry"),
            "dte": short_dte,
            "delta": pos.get("delta"),
            "assignment_prob": pos.get("assignment_prob"),
            "profit_per_day": pos.get("profit_per_day"),
            "pnl_if_assigned": pnl_if_assigned,
        }

    result = {"current": _entry(current)}
    for i, roll in enumerate(rolls, 1):
        result[f"roll_{i}"] = _entry(roll)
    return result


def find_roll_expiration_targets(
    current_expiry: str,
    available_expirations: list[str],
    max_expiry: str,
) -> list[str]:
    """Return up to 2 expirations: nearest to 7d and 14d after current_expiry."""
    current_date = datetime.strptime(current_expiry, "%Y%m%d").date()
    candidates = sorted(
        [e for e in available_expirations if e > current_expiry and e <= max_expiry]
    )
    targets = [current_date + timedelta(days=7), current_date + timedelta(days=14)]
    result = []
    for target in targets:
        if not candidates:
            break
        best = min(
            candidates,
            key=lambda e: abs((datetime.strptime(e, "%Y%m%d").date() - target).days),
        )
        if best not in result:
            result.append(best)
    return result


# ===========================================================================
# YAHOO FINANCE DATA (outside trading hours — separated from IBKR below)
# ===========================================================================


def _ibkr_to_yf_date(expiry: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD."""
    return f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:8]}"


def _yf_to_ibkr_date(expiry: str) -> str:
    """Convert YYYY-MM-DD to YYYYMMDD."""
    return expiry.replace("-", "")


def _closest_yf_expiry(target_ibkr: str, yf_expirations: list[str]) -> str | None:
    """Return the yf expiry string (YYYY-MM-DD) closest to an IBKR expiry string."""
    if not yf_expirations:
        return None
    target = datetime.strptime(target_ibkr, "%Y%m%d").date()
    return min(
        yf_expirations,
        key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d").date() - target).days),
    )


async def _fetch_yf_spot_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch last prices from Yahoo Finance for all symbols in parallel."""

    async def _one(sym: str) -> tuple[str, float | None]:
        def _sync() -> float | None:
            import yfinance as yf

            fi = yf.Ticker(sym).fast_info
            return fi.get("lastPrice") or fi.get("regularMarketPrice") or fi.get("previousClose")

        price = await asyncio.to_thread(_sync)
        return sym, price

    pairs = await asyncio.gather(*[_one(sym) for sym in symbols])
    return {sym: float(p) for sym, p in pairs if p and float(p) > 0}


async def _fetch_yf_option_quote(
    symbol: str, expiry_ibkr: str, strike: float, right: str
) -> dict | None:
    """Fetch a single option quote from Yahoo Finance (stale, outside hours)."""

    def _sync() -> dict | None:
        import yfinance as yf

        t = yf.Ticker(symbol)
        available = list(t.options)
        if not available:
            return None
        closest = _closest_yf_expiry(expiry_ibkr, available)
        if not closest:
            return None
        chain = t.option_chain(closest)
        df = chain.calls if right == "C" else chain.puts
        candidates = df[abs(df["strike"] - strike) < 0.01]
        if candidates.empty:
            candidates = df.iloc[(df["strike"] - strike).abs().argsort()[:1]]
        if candidates.empty:
            return None
        row = candidates.iloc[0]
        bid = safe_value(row.get("bid"))
        ask = safe_value(row.get("ask"))
        last = safe_value(row.get("lastPrice"))
        iv_raw = safe_value(row.get("impliedVolatility"))
        return {
            "bid": round(float(bid), 2) if bid else None,
            "ask": round(float(ask), 2) if ask else None,
            "last": round(float(last), 2) if last else None,
            "ib_delta": None,
            "ib_iv_pct": round(float(iv_raw) * 100, 2) if iv_raw else None,
            "stale": True,
        }

    return await asyncio.to_thread(_sync)


async def _fetch_yf_option_chain_batch(symbol: str, expiry_ibkr: str, spot: float) -> list[dict]:
    """Fetch call option quotes from Yahoo Finance for a given expiry, filtered by spot ±25%."""

    def _sync() -> list[dict]:
        import yfinance as yf

        t = yf.Ticker(symbol)
        available = list(t.options)
        if not available:
            return []
        closest = _closest_yf_expiry(expiry_ibkr, available)
        if not closest:
            return []
        df = t.option_chain(closest).calls
        if spot > 0:
            df = df[(df["strike"] >= spot * 0.95) & (df["strike"] <= spot * 1.25)]
        results = []
        for _, row in df.iterrows():
            bid = safe_value(row.get("bid"))
            ask = safe_value(row.get("ask"))
            last = safe_value(row.get("lastPrice"))
            mid = (float(bid) + float(ask)) / 2 if bid and ask else (float(bid or ask or 0))
            results.append(
                {
                    "strike": float(row["strike"]),
                    "expiry": expiry_ibkr,
                    "bid": round(float(bid), 2) if bid else None,
                    "ask": round(float(ask), 2) if ask else None,
                    "mid": round(mid, 2),
                    "last": round(float(last), 2) if last else None,
                    "stale": True,
                }
            )
        return sorted(results, key=lambda x: x["strike"])

    return await asyncio.to_thread(_sync)


async def _fetch_earnings_dates(symbols: list[str]) -> dict[str, dict]:
    """Fetch next earnings date and timing for all symbols in parallel via Yahoo Finance."""
    from trading_skills.earnings import get_earnings_info

    async def _one(sym: str) -> tuple[str, dict]:
        info = await asyncio.to_thread(get_earnings_info, sym)
        return sym, {"date": info.get("earnings_date"), "timing": info.get("timing")}

    pairs = await asyncio.gather(*[_one(sym) for sym in symbols])
    return dict(pairs)


async def _fetch_yf_chain_expirations(symbol: str) -> list[str]:
    """Return available option expirations in YYYYMMDD format from Yahoo Finance."""

    def _sync() -> list[str]:
        import yfinance as yf

        return [_yf_to_ibkr_date(e) for e in yf.Ticker(symbol).options]

    return await asyncio.to_thread(_sync)


# ===========================================================================
# IBKR DATA FETCHING
# ===========================================================================


async def _fetch_single_option_quote(
    ib, symbol: str, strike: float, expiry: str, right: str
) -> dict | None:
    """Fetch bid/ask/last and model Greeks for a single option contract.

    Uses streaming market data (not snapshot) to avoid hanging outside trading hours
    when IB's snapshot mode never completes for options with no active market.
    """
    from ib_async import Option

    contract = Option(symbol, expiry, strike, right, "SMART")
    qualified = await fetch_with_timeout(ib.qualifyContractsAsync(contract), timeout=10, default=[])
    if not qualified or not qualified[0] or not getattr(qualified[0], "conId", None):
        return None

    qc = qualified[0]
    ticker = ib.reqMktData(qc, "", False, False)
    await asyncio.sleep(3)
    ib.cancelMktData(qc)

    bid = ticker.bid if ticker.bid and ticker.bid > 0 else None
    ask = ticker.ask if ticker.ask and ticker.ask > 0 else None
    last = ticker.last if ticker.last and ticker.last > 0 else None

    ib_delta = None
    ib_iv_pct = None
    if ticker.modelGreeks:
        if ticker.modelGreeks.delta:
            ib_delta = round(ticker.modelGreeks.delta, 4)
        if ticker.modelGreeks.impliedVol:
            ib_iv_pct = round(ticker.modelGreeks.impliedVol * 100, 2)

    return {
        "bid": round(bid, 2) if bid is not None else None,
        "ask": round(ask, 2) if ask is not None else None,
        "last": round(last, 2) if last is not None else None,
        "ib_delta": ib_delta,
        "ib_iv_pct": ib_iv_pct,
        "stale": bid is None and ask is None and last is not None,
    }


async def _fetch_option_quotes_batch(
    ib, symbol: str, expiry: str, strikes: list[float], right: str
) -> list[dict]:
    """Fetch option quotes for multiple strikes at one expiry.

    Uses streaming market data (not snapshot) to avoid hanging outside trading hours.
    """
    import logging

    from ib_async import Option

    contracts = [Option(symbol, expiry, s, right, "SMART") for s in strikes]

    ib_logger = logging.getLogger("ib_async")
    prev_level = ib_logger.level
    ib_logger.setLevel(logging.CRITICAL)

    try:
        qualified = await fetch_with_timeout(
            ib.qualifyContractsAsync(*contracts), timeout=15, default=[]
        )
    finally:
        ib_logger.setLevel(prev_level)

    qualified = [c for c in (qualified or []) if c is not None and getattr(c, "conId", None)]
    if not qualified:
        return []

    tickers = [ib.reqMktData(qc, "", False, False) for qc in qualified]
    await asyncio.sleep(3)
    for qc in qualified:
        ib.cancelMktData(qc)

    results = []
    for t in tickers:
        if not t.contract:
            continue
        bid = t.bid if t.bid and t.bid > 0 else None
        ask = t.ask if t.ask and t.ask > 0 else None
        mid = (bid + ask) / 2 if bid and ask else (bid or ask or 0)
        last = t.last if t.last and t.last > 0 else None
        results.append(
            {
                "strike": t.contract.strike,
                "expiry": expiry,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": last,
                "stale": bid is None and ask is None and last is not None,
            }
        )
    return sorted(results, key=lambda x: x["strike"])


def filter_spreads_by_symbols(spreads: list[dict], symbols: list[str] | None) -> list[dict]:
    """Return only spreads whose symbol is in the given list (case-insensitive).

    Returns all spreads unchanged when symbols is None.
    """
    if symbols is None:
        return spreads
    upper = {s.upper() for s in symbols}
    return [s for s in spreads if s["symbol"].upper() in upper]


def _identify_pmcc_spreads(normalized: list[dict]) -> list[dict]:
    """Identify PMCC (diagonal call) spreads: long LEAPS + short near-term call, same qty."""
    by_symbol = defaultdict(list)
    for pos in normalized:
        if pos["sec_type"] == "OPT" and pos.get("right") == "C":
            by_symbol[pos["symbol"]].append(pos)

    spreads = []
    for symbol, positions in by_symbol.items():
        longs = sorted(
            [p for p in positions if p["quantity"] > 0],
            key=lambda x: x.get("expiry", ""),
            reverse=True,
        )
        shorts = sorted(
            [p for p in positions if p["quantity"] < 0],
            key=lambda x: x.get("expiry", ""),
        )

        used = set()
        for long_pos in longs:
            for j, short_pos in enumerate(shorts):
                if j in used:
                    continue
                if (
                    long_pos["expiry"] > short_pos["expiry"]
                    and abs(long_pos["quantity"]) == abs(short_pos["quantity"])
                    and long_pos["strike"] < short_pos["strike"]
                ):
                    spreads.append(
                        {
                            "symbol": symbol,
                            "long": long_pos,
                            "short": short_pos,
                            "qty": int(abs(long_pos["quantity"])),
                        }
                    )
                    used.add(j)
                    break

    return spreads


async def _get_chain_params(ib, symbol: str) -> dict:
    """Fetch option chain expirations and strikes from IBKR."""
    from ib_async import Stock

    stock = Stock(symbol, "SMART", "USD")
    await fetch_with_timeout(ib.qualifyContractsAsync(stock), timeout=10, default=[])
    chains = await fetch_with_timeout(
        ib.reqSecDefOptParamsAsync(symbol, "", "STK", stock.conId), timeout=15, default=[]
    )
    if not chains:
        return {"expirations": [], "strikes": []}
    chain = best_option_chain(chains)
    return {
        "expirations": sorted(chain.expirations),
        "strikes": sorted(chain.strikes),
    }


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================


async def get_pmcc_data(
    port: int = 7496,
    account: str | None = None,
    min_roll_dte: int = 7,
    price_mode: str = "mid",
    symbols: list[str] | None = None,
) -> dict:
    """Fetch all PMCC positions then run analytics.

    During trading hours all data comes from IBKR.
    Outside trading hours portfolio comes from IBKR; spot prices, option quotes,
    and chain data come from Yahoo Finance to avoid hanging on stale IBKR snapshots.

    All market data for a given analysis phase is fetched in a single asyncio.gather
    call before any analytics begin.
    """
    try:
        async with ib_connection(port, CLIENT_IDS["pmcc_advisor"]) as ib:
            ib.reqMarketDataType(4)
            await asyncio.sleep(2)

            managed = ib.managedAccounts()
            if account and account not in managed:
                return {
                    "generated_at": generated_at_str(),
                    "data_delay": "unknown",
                    "error": f"Account {account} not found. Available: {managed}",
                }
            accounts = [account] if account else list(managed)

            raw = await fetch_positions(ib, account=account)
            normalized = normalize_positions(raw)
            spreads = _identify_pmcc_spreads(normalized)
            spreads = filter_spreads_by_symbols(spreads, symbols)

            if not spreads:
                return {
                    "generated_at": generated_at_str(),
                    "data_delay": "real-time",
                    "accounts": accounts,
                    "symbols_filter": [s.upper() for s in symbols] if symbols else None,
                    "spreads": [],
                    "message": "No PMCC (diagonal call spread) positions found",
                }

            unique_symbols = list({s["symbol"] for s in spreads})
            n = len(spreads)
            live = is_trading_now()

            # ----------------------------------------------------------------
            # PARALLEL PHASE 1: spot prices + both option leg quotes + chain data
            # ----------------------------------------------------------------
            if live:
                phase1 = await asyncio.gather(
                    fetch_spot_prices(ib, unique_symbols),
                    *[
                        _fetch_single_option_quote(
                            ib, s["symbol"], s["short"]["strike"], s["short"]["expiry"], "C"
                        )
                        for s in spreads
                    ],
                    *[
                        _fetch_single_option_quote(
                            ib, s["symbol"], s["long"]["strike"], s["long"]["expiry"], "C"
                        )
                        for s in spreads
                    ],
                    *[_get_chain_params(ib, sym) for sym in unique_symbols],
                    _fetch_earnings_dates(unique_symbols),
                )
            else:
                phase1 = await asyncio.gather(
                    _fetch_yf_spot_prices(unique_symbols),
                    *[
                        _fetch_yf_option_quote(
                            s["symbol"], s["short"]["expiry"], s["short"]["strike"], "C"
                        )
                        for s in spreads
                    ],
                    *[
                        _fetch_yf_option_quote(
                            s["symbol"], s["long"]["expiry"], s["long"]["strike"], "C"
                        )
                        for s in spreads
                    ],
                    *[_fetch_yf_chain_expirations(sym) for sym in unique_symbols],
                    _fetch_earnings_dates(unique_symbols),
                )

            spot_prices: dict[str, float] = phase1[0]
            short_quotes: list = list(phase1[1 : n + 1])
            long_quotes: list = list(phase1[n + 1 : 2 * n + 1])
            chain_data_by_symbol: dict = {
                sym: phase1[2 * n + 1 + i] for i, sym in enumerate(unique_symbols)
            }
            earnings_by_symbol: dict[str, dict] = phase1[2 * n + 1 + len(unique_symbols)]

            # ----------------------------------------------------------------
            # Determine roll expiration targets (7d / 14d windows)
            # ----------------------------------------------------------------
            roll_exps_by_spread: list[list[str]] = []
            for spread in spreads:
                sym = spread["symbol"]
                cd = chain_data_by_symbol.get(sym)
                expirations = cd.get("expirations", []) if isinstance(cd, dict) else (cd or [])
                roll_exps_by_spread.append(
                    find_roll_expiration_targets(
                        current_expiry=spread["short"]["expiry"],
                        available_expirations=sorted(expirations),
                        max_expiry=spread["long"]["expiry"],
                    )
                )

            # ----------------------------------------------------------------
            # PARALLEL PHASE 2: roll chains for all spreads
            # ----------------------------------------------------------------
            roll_chain_tasks: list = []
            roll_chain_keys: list[tuple[int, str]] = []
            for i, (spread, roll_exps) in enumerate(zip(spreads, roll_exps_by_spread)):
                sym = spread["symbol"]
                spot = spot_prices.get(sym, 0)
                if live:
                    cd = chain_data_by_symbol.get(sym, {})
                    all_strikes = cd.get("strikes", []) if isinstance(cd, dict) else []
                    roll_strikes = (
                        [s for s in all_strikes if spot * 0.95 <= s <= spot * 1.25] if spot else []
                    )
                    for exp in roll_exps:
                        roll_chain_tasks.append(
                            _fetch_option_quotes_batch(ib, sym, exp, roll_strikes, "C")
                        )
                        roll_chain_keys.append((i, exp))
                else:
                    for exp in roll_exps:
                        roll_chain_tasks.append(_fetch_yf_option_chain_batch(sym, exp, spot))
                        roll_chain_keys.append((i, exp))

            roll_chain_results = await asyncio.gather(*roll_chain_tasks) if roll_chain_tasks else []

            roll_chains_by_spread: list[dict[str, list]] = [{} for _ in spreads]
            for (spread_idx, exp), quotes in zip(roll_chain_keys, roll_chain_results):
                if quotes:
                    roll_chains_by_spread[spread_idx][exp] = quotes

            # ----------------------------------------------------------------
            # ANALYTICS
            # ----------------------------------------------------------------
            data_delay = "real-time" if live else "stalled - using last price"
            results = []

            for i, spread in enumerate(spreads):
                symbol = spread["symbol"]
                long_pos = spread["long"]
                short_pos = spread["short"]
                qty = spread["qty"]
                spot = spot_prices.get(symbol)
                if not spot:
                    continue

                short_quote = short_quotes[i]
                long_quote = long_quotes[i]
                roll_chains = roll_chains_by_spread[i]

                long_dte = days_to_expiry(long_pos["expiry"])
                short_dte = days_to_expiry(short_pos["expiry"])

                short_price = get_option_price(short_quote or {}, price_mode)
                long_price = get_option_price(long_quote or {}, price_mode)

                if (short_quote and short_quote.get("stale")) or (
                    long_quote and long_quote.get("stale")
                ):
                    data_delay = "stalled - using last price"

                # Short leg analytics
                short_iv = None
                if short_price:
                    short_iv = calc_iv(short_price, spot, short_pos["strike"], short_dte, "C")
                if not short_iv and short_quote and short_quote.get("ib_iv_pct"):
                    short_iv = short_quote["ib_iv_pct"] / 100
                if not short_iv:
                    short_iv = estimate_iv(
                        spot, short_pos["strike"], max(short_dte, 1 / 24) / 365, "call"
                    )
                    data_delay = "stalled - using estimated IV"

                short_delta = calc_delta(spot, short_pos["strike"], short_dte, short_iv, "C")
                short_assign_prob = calc_assignment_prob(
                    spot, short_pos["strike"], short_dte, short_iv, "C"
                )

                # Long leg analytics
                long_iv = None
                if long_price:
                    long_iv = calc_iv(long_price, spot, long_pos["strike"], long_dte, "C")
                if not long_iv and long_quote and long_quote.get("ib_iv_pct"):
                    long_iv = long_quote["ib_iv_pct"] / 100
                if not long_iv:
                    t = max(long_dte, 1 / 24) / 365
                    long_iv = estimate_iv(spot, long_pos["strike"], t, "call")

                # Daily P&L table — next 5 trading days, optimal-exit spot per day
                daily_pnl = []
                if short_dte >= 0:
                    daily_pnl = calc_daily_pnl_table(
                        long_strike=long_pos["strike"],
                        long_dte=long_dte,
                        long_cost=long_pos["avg_cost"],
                        long_iv=long_iv,
                        short_strike=short_pos["strike"],
                        short_dte=short_dte,
                        short_premium=abs(short_pos["avg_cost"]),
                        short_iv=short_iv,
                        qty=qty,
                        spot=spot,
                        right="C",
                    )

                # Roll candidates — from 7d/14d roll windows only, capped by LEAPS expiry
                rolls = []
                if short_price is not None:
                    rolls = find_best_rolls(
                        current_short_strike=short_pos["strike"],
                        current_short_expiry=short_pos["expiry"],
                        current_short_dte=short_dte,
                        current_short_price=short_price,
                        current_delta=abs(short_delta),
                        roll_chains=roll_chains,
                        spot=spot,
                        long_strike=long_pos["strike"],
                        long_cost=long_pos["avg_cost"],
                        long_dte=long_dte,
                        long_iv=long_iv,
                        qty=qty,
                        min_roll_dte=min_roll_dte,
                        price_mode=price_mode,
                    )

                earnings_info = earnings_by_symbol.get(symbol, {})
                earnings_warn = check_earnings_warning(
                    earnings_date=earnings_info.get("date"),
                    earnings_timing=earnings_info.get("timing"),
                    short_expiry=short_pos["expiry"],
                    roll_candidates=rolls,
                )

                current_short_summary = {
                    "strike": short_pos["strike"],
                    "expiry": short_pos["expiry"],
                    "dte": short_dte,
                    "delta": round(abs(short_delta), 4),
                    "assignment_prob": round(short_assign_prob * 100, 1),
                    "price": round(short_price, 2) if short_price else None,
                    "profit_per_day": round(
                        calc_profit_per_day(abs(short_pos["avg_cost"]), short_dte, short_price), 4
                    ),
                    "total_premium": abs(short_pos["avg_cost"]),
                }
                comparison = build_comparison_table(
                    current=current_short_summary,
                    rolls=rolls,
                    long_pos=long_pos,
                    long_dte=long_dte,
                    long_iv=long_iv,
                    qty=qty,
                )

                results.append(
                    {
                        "symbol": symbol,
                        "account": account or accounts[0],
                        "qty": qty,
                        "underlying_price": round(spot, 2),
                        "leaps_expiry": long_pos["expiry"],
                        "earnings": earnings_warn,
                        "long": {
                            "strike": long_pos["strike"],
                            "expiry": long_pos["expiry"],
                            "dte": long_dte,
                            "avg_cost": long_pos["avg_cost"],
                            "current_price": round(long_price, 2) if long_price else None,
                            "iv_pct": round(long_iv * 100, 1) if long_iv else None,
                            "ib_delta": long_quote.get("ib_delta") if long_quote else None,
                            "ib_iv_pct": long_quote.get("ib_iv_pct") if long_quote else None,
                        },
                        "short": {
                            "strike": short_pos["strike"],
                            "expiry": short_pos["expiry"],
                            "dte": short_dte,
                            "premium_received": abs(short_pos["avg_cost"]),
                            "current_price": round(short_price, 2) if short_price else None,
                            "iv_pct": round(short_iv * 100, 1) if short_iv else None,
                            "delta": round(abs(short_delta), 4),
                            "assignment_prob_pct": round(short_assign_prob * 100, 1),
                            "ib_delta": short_quote.get("ib_delta") if short_quote else None,
                            "ib_iv_pct": short_quote.get("ib_iv_pct") if short_quote else None,
                        },
                        "daily_pnl": daily_pnl,
                        "roll_candidates": rolls,
                        "comparison": comparison,
                    }
                )

            return {
                "generated_at": generated_at_str(),
                "data_delay": data_delay,
                "accounts": accounts,
                "symbols_filter": [s.upper() for s in symbols] if symbols else None,
                "price_mode": price_mode,
                "min_roll_dte": min_roll_dte,
                "spreads": results,
            }

    except ConnectionError as e:
        return {
            "generated_at": generated_at_str(),
            "data_delay": "unknown",
            "error": f"{e}. Is TWS/Gateway running?",
        }

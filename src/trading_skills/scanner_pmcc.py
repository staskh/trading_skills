# ABOUTME: Scans symbols for PMCC suitability based on option chain quality.
# ABOUTME: Scores delta accuracy, liquidity, spread, IV, yield, trend, and earnings proximity.

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from trading_skills.black_scholes import (
    black_scholes_delta,
    black_scholes_price,
    implied_volatility,
)
from trading_skills.earnings import get_next_earnings_date
from trading_skills.technicals import compute_raw_indicators
from trading_skills.utils import get_current_price

_NY = ZoneInfo("America/New_York")


def _to_int(val, default=0) -> int:
    """Convert option field to int, treating None and NaN as default."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return int(val)


def format_scan_results(results: list[dict]) -> dict:
    """Sort and wrap PMCC scan results into output dict.

    Filters valid results (with pmcc_score), sorts by score then yield,
    and separates errors.
    """
    valid_results = [r for r in results if "pmcc_score" in r]
    valid_results.sort(
        key=lambda x: (
            x["pmcc_score"],
            x.get("metrics", {}).get("annual_yield_est_pct", 0),
        ),
        reverse=True,
    )

    return {
        "scan_date": datetime.now(_NY).strftime("%Y-%m-%d %H:%M ET"),
        "count": len(valid_results),
        "results": valid_results,
        "errors": [r for r in results if "error" in r],
    }


def find_strike_by_delta(
    chain, current_price, target_delta, expiry_days, iv, r=0.05, min_strike=None, max_strike=None
):
    """Find strike closest to target delta with optional strike constraints.

    Falls back to lastPrice when bid=ask=0 (e.g. off-market hours).
    """
    T = expiry_days / 365
    best_strike = None
    best_delta_diff = float("inf")
    best_option = None

    for _, row in chain.iterrows():
        strike = row["strike"]

        bid = row.get("bid", 0) or 0
        ask = row.get("ask", 0) or 0
        last = row.get("lastPrice", 0) or 0

        if pd.isna(bid):
            bid = 0.0
        if pd.isna(ask):
            ask = 0.0
        if pd.isna(last):
            last = 0.0

        # Skip if no price reference at all
        if bid <= 0 and ask <= 0 and last <= 0:
            continue

        if min_strike is not None and strike < min_strike:
            continue
        if max_strike is not None and strike > max_strike:
            continue

        # Use bid/ask mid when available, else fall back to lastPrice
        if bid > 0 or ask > 0:
            effective_mid = (bid + ask) / 2
        else:
            effective_mid = last

        if bid > 0 or ask > 0:
            # Live market data: use yfinance IV with fallback to avg_iv
            option_iv = row.get("impliedVolatility", iv)
            if pd.isna(option_iv) or option_iv <= 0 or option_iv < 0.01:
                option_iv = iv
        else:
            # Off-hours: derive IV from lastPrice using T from lastTradeDate to expiry
            option_iv = iv  # default
            if last > 0:
                last_trade = row.get("lastTradeDate")
                if last_trade is not None and not pd.isna(last_trade):
                    trade_ts = pd.Timestamp(last_trade)
                    if trade_ts.tzinfo is not None:
                        trade_ts = trade_ts.tz_convert(_NY)
                    else:
                        trade_ts = trade_ts.tz_localize(_NY)
                    trade_date = trade_ts.date()
                    current_date = datetime.now(_NY).date()
                    days_since_trade = (current_date - trade_date).days
                    T_for_iv = T + days_since_trade / 365
                    if T_for_iv > 0:
                        iv_from_last = implied_volatility(
                            last, current_price, strike, T_for_iv, r, "call"
                        )
                        if iv_from_last is not None and iv_from_last >= 0.01:
                            option_iv = iv_from_last

        delta = black_scholes_delta(current_price, strike, T, r, option_iv, "call")
        delta_diff = abs(delta - target_delta)

        if delta_diff < best_delta_diff:
            best_delta_diff = delta_diff
            best_strike = strike
            best_option = row.copy()
            best_option["calculated_delta"] = delta
            best_option["effective_mid"] = effective_mid

    return best_strike, best_option


def compute_atm_iv(
    atm_calls: pd.DataFrame, current_price: float, expiry_date: str, r: float = 0.05
) -> float:
    """Compute average ATM implied volatility from option chain data.

    If yfinance's impliedVolatility is unreliable (< 1%), falls back to computing
    IV from lastPrice using the Black-Scholes solver, with T measured from
    lastTradeDate to expiry.

    Returns 0.30 as a default when no valid IV can be computed.
    """
    if atm_calls.empty:
        return 0.30

    raw_iv = atm_calls["impliedVolatility"].mean()
    if not pd.isna(raw_iv) and raw_iv >= 0.01:
        return raw_iv

    # Fallback: compute IV from lastPrice at lastTradeDate
    expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d").date()
    ivs = []

    for _, row in atm_calls.iterrows():
        last_price = row.get("lastPrice", 0) or 0
        if pd.isna(last_price) or last_price <= 0:
            continue

        last_trade = row.get("lastTradeDate")
        if last_trade is None or (hasattr(last_trade, "__bool__") and pd.isna(last_trade)):
            continue

        trade_date = last_trade.date() if hasattr(last_trade, "date") else last_trade
        T = (expiry_dt - trade_date).days / 365
        if T <= 0:
            continue

        iv = implied_volatility(last_price, current_price, row["strike"], T, r, "call")
        if iv is not None and iv >= 0.01:
            ivs.append(iv)

    return sum(ivs) / len(ivs) if ivs else 0.30


def compute_trend_score(price: float, raw: dict) -> tuple[float, dict]:
    """Score bullish/bearish trend based on SMA50, RSI, and MACD.

    Returns (score_delta, breakdown). Range: -2.0 to +2.0.
    """
    delta = 0.0
    breakdown = {}

    sma50 = raw.get("sma50")
    if sma50 is not None:
        if price > sma50:
            delta += 1.0
            breakdown["sma50"] = f"+1.0 (price {price:.2f} > SMA50 {sma50:.2f})"
        else:
            delta -= 1.0
            breakdown["sma50"] = f"-1.0 (price {price:.2f} < SMA50 {sma50:.2f})"

    rsi = raw.get("rsi")
    if rsi is not None:
        if rsi > 50:
            delta += 0.5
            breakdown["rsi"] = f"+0.5 (RSI {rsi:.1f} > 50)"
        else:
            delta -= 0.5
            breakdown["rsi"] = f"-0.5 (RSI {rsi:.1f} < 50)"

    macd_line = raw.get("macd_line")
    macd_signal = raw.get("macd_signal")
    if macd_line is not None and macd_signal is not None:
        if macd_line > macd_signal:
            delta += 0.5
            breakdown["macd"] = f"+0.5 (MACD {macd_line:.3f} > signal {macd_signal:.3f})"
        else:
            delta -= 0.5
            breakdown["macd"] = f"-0.5 (MACD {macd_line:.3f} < signal {macd_signal:.3f})"

    return round(delta, 1), breakdown


def compute_earnings_score(earnings_date_str: str | None, short_days: int) -> tuple[float, dict]:
    """Score earnings proximity relative to short call expiry.

    Returns (score_delta, breakdown).
    - Earnings > 45d away: +1.0 (clear decay runway)
    - Earnings within short expiry: -2.0 (IV crush / gap risk)
    - Earnings between short expiry and 45d: -1.0
    - No date or past: 0.0
    """
    if not earnings_date_str:
        return 0.0, {"earnings": "0.0 (no earnings date)"}

    try:
        today = datetime.now().date()
        earnings_date = datetime.strptime(earnings_date_str, "%Y-%m-%d").date()
        days_to_earnings = (earnings_date - today).days

        if days_to_earnings < 0:
            return 0.0, {"earnings": "0.0 (earnings already passed)"}

        if days_to_earnings > 45:
            return 1.0, {
                "earnings": f"+1.0 (earnings {days_to_earnings}d away, clear decay runway)"
            }
        elif days_to_earnings <= short_days:
            return -2.0, {
                "earnings": f"-2.0 (earnings in {days_to_earnings}d, within short call expiry)"
            }
        else:
            return -1.0, {"earnings": f"-1.0 (earnings in {days_to_earnings}d, within 45 days)"}

    except (ValueError, TypeError):
        return 0.0, {"earnings": "0.0 (invalid earnings date)"}


def compute_base_score(
    actual_leaps_delta: float,
    actual_short_delta: float,
    leaps_liquidity: int,
    short_liquidity: int,
    leaps_spread_pct: float,
    short_spread_pct: float,
    avg_iv: float,
    annual_yield_est: float,
    leaps_delta_target: float = 0.80,
    short_delta_target: float = 0.20,
) -> tuple[float, dict]:
    """Score options structure: delta accuracy, liquidity, spread, IV, and yield.

    Returns (score, breakdown). Max score is 11.
    """
    score = 0.0
    bd = {}

    # LEAPS delta accuracy
    if leaps_delta_target - 0.05 <= actual_leaps_delta <= leaps_delta_target + 0.05:
        d = 2.0
        bd["leaps_delta"] = (
            f"+2.0 (LEAPS delta {actual_leaps_delta:.3f} within ±0.05 of {leaps_delta_target})"
        )
    elif leaps_delta_target - 0.10 <= actual_leaps_delta <= leaps_delta_target + 0.10:
        d = 1.0
        bd["leaps_delta"] = (
            f"+1.0 (LEAPS delta {actual_leaps_delta:.3f} within ±0.10 of {leaps_delta_target})"
        )
    else:
        d = 0.0
        bd["leaps_delta"] = (
            f"0.0 (LEAPS delta {actual_leaps_delta:.3f} outside ±0.10 of {leaps_delta_target})"
        )
    bd["leaps_delta_delta"] = d
    score += d

    # Short delta accuracy
    if short_delta_target - 0.05 <= actual_short_delta <= short_delta_target + 0.05:
        d = 1.0
        bd["short_delta"] = (
            f"+1.0 (short delta {actual_short_delta:.3f} within ±0.05 of {short_delta_target})"
        )
    elif short_delta_target - 0.10 <= actual_short_delta <= short_delta_target + 0.10:
        d = 0.5
        bd["short_delta"] = (
            f"+0.5 (short delta {actual_short_delta:.3f} within ±0.10 of {short_delta_target})"
        )
    else:
        d = 0.0
        bd["short_delta"] = (
            f"0.0 (short delta {actual_short_delta:.3f} outside ±0.10 of {short_delta_target})"
        )
    bd["short_delta_delta"] = d
    score += d

    # LEAPS liquidity
    if leaps_liquidity > 100:
        d = 1.0
        bd["leaps_liquidity"] = f"+1.0 (LEAPS vol+OI {leaps_liquidity} > 100)"
    elif leaps_liquidity > 20:
        d = 0.5
        bd["leaps_liquidity"] = f"+0.5 (LEAPS vol+OI {leaps_liquidity} > 20)"
    else:
        d = 0.0
        bd["leaps_liquidity"] = f"0.0 (LEAPS vol+OI {leaps_liquidity} <= 20)"
    bd["leaps_liquidity_delta"] = d
    score += d

    # Short liquidity
    if short_liquidity > 500:
        d = 1.0
        bd["short_liquidity"] = f"+1.0 (short vol+OI {short_liquidity} > 500)"
    elif short_liquidity > 100:
        d = 0.5
        bd["short_liquidity"] = f"+0.5 (short vol+OI {short_liquidity} > 100)"
    else:
        d = 0.0
        bd["short_liquidity"] = f"0.0 (short vol+OI {short_liquidity} <= 100)"
    bd["short_liquidity_delta"] = d
    score += d

    # LEAPS spread
    if leaps_spread_pct < 5:
        d = 1.0
        bd["leaps_spread"] = f"+1.0 (LEAPS spread {leaps_spread_pct:.1f}% < 5%)"
    elif leaps_spread_pct < 10:
        d = 0.5
        bd["leaps_spread"] = f"+0.5 (LEAPS spread {leaps_spread_pct:.1f}% < 10%)"
    else:
        d = 0.0
        bd["leaps_spread"] = f"0.0 (LEAPS spread {leaps_spread_pct:.1f}% >= 10%)"
    bd["leaps_spread_delta"] = d
    score += d

    # Short spread
    if short_spread_pct < 10:
        d = 1.0
        bd["short_spread"] = f"+1.0 (short spread {short_spread_pct:.1f}% < 10%)"
    elif short_spread_pct < 20:
        d = 0.5
        bd["short_spread"] = f"+0.5 (short spread {short_spread_pct:.1f}% < 20%)"
    else:
        d = 0.0
        bd["short_spread"] = f"0.0 (short spread {short_spread_pct:.1f}% >= 20%)"
    bd["short_spread_delta"] = d
    score += d

    # IV level
    iv_pct = avg_iv * 100
    if 0.25 <= avg_iv <= 0.50:
        d = 2.0
        bd["iv"] = f"+2.0 (IV {iv_pct:.1f}% in ideal range 25-50%)"
    elif 0.20 <= avg_iv <= 0.60:
        d = 1.0
        bd["iv"] = f"+1.0 (IV {iv_pct:.1f}% in acceptable range 20-60%)"
    else:
        d = 0.0
        bd["iv"] = f"0.0 (IV {iv_pct:.1f}% outside range 20-60%)"
    bd["iv_delta"] = d
    score += d

    # Annual yield
    if annual_yield_est > 50:
        d = 2.0
        bd["yield"] = f"+2.0 (annual yield {annual_yield_est:.1f}% > 50%)"
    elif annual_yield_est > 30:
        d = 1.0
        bd["yield"] = f"+1.0 (annual yield {annual_yield_est:.1f}% > 30%)"
    elif annual_yield_est > 15:
        d = 0.5
        bd["yield"] = f"+0.5 (annual yield {annual_yield_est:.1f}% > 15%)"
    else:
        d = 0.0
        bd["yield"] = f"0.0 (annual yield {annual_yield_est:.1f}% <= 15%)"
    bd["yield_delta"] = d
    score += d

    return round(score, 1), bd


def analyze_pmcc(
    symbol: str,
    min_leaps_days: int = 270,
    short_days_range: tuple = (7, 21),
    leaps_delta: float = 0.80,
    short_delta: float = 0.20,
    ticker=None,
) -> dict | None:
    """Analyze a symbol for PMCC suitability."""
    try:
        ticker = ticker or yf.Ticker(symbol)
        info = ticker.info
        current_price = get_current_price(info)

        if not current_price:
            hist = ticker.history(period="5d")
            if hist.empty:
                return None
            current_price = hist["Close"].iloc[-1]

        expirations = ticker.options
        if not expirations:
            return {"symbol": symbol, "error": "No options available"}

        today = datetime.now()

        # Find LEAPS expiry
        leaps_expiry = None
        leaps_days = 0
        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_to_exp = (exp_date - today).days
            if days_to_exp >= min_leaps_days:
                leaps_expiry = exp
                leaps_days = days_to_exp
                break

        if not leaps_expiry:
            return {"symbol": symbol, "error": f"No LEAPS expiry >= {min_leaps_days} days found"}

        # Find short-term expiry
        short_expiry = None
        short_days = 0
        for exp in expirations:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_to_exp = (exp_date - today).days
            if short_days_range[0] <= days_to_exp <= short_days_range[1]:
                short_expiry = exp
                short_days = days_to_exp
                break

        if not short_expiry:
            for exp in expirations:
                exp_date = datetime.strptime(exp, "%Y-%m-%d")
                days_to_exp = (exp_date - today).days
                if 5 <= days_to_exp <= 30:
                    short_expiry = exp
                    short_days = days_to_exp
                    break

        if not short_expiry:
            return {"symbol": symbol, "error": "No suitable short-term expiry found"}

        leaps_chain = ticker.option_chain(leaps_expiry)
        short_chain = ticker.option_chain(short_expiry)

        # Estimate IV from ATM options, with fallback to lastPrice-based IV
        atm_calls = leaps_chain.calls[
            (leaps_chain.calls["strike"] >= current_price * 0.95)
            & (leaps_chain.calls["strike"] <= current_price * 1.05)
        ]
        avg_iv = compute_atm_iv(atm_calls, current_price, leaps_expiry)

        # Find LEAPS call
        leaps_strike, leaps_option = find_strike_by_delta(
            leaps_chain.calls,
            current_price,
            leaps_delta,
            leaps_days,
            avg_iv,
            max_strike=current_price * 1.02,
        )

        if leaps_option is None:
            return {
                "symbol": symbol,
                "error": f"Could not find suitable LEAPS strike with delta ~{leaps_delta}",
            }

        # Find short call (must be above LEAPS strike)
        short_strike, short_option = find_strike_by_delta(
            short_chain.calls,
            current_price,
            short_delta,
            short_days,
            avg_iv,
            min_strike=leaps_strike + 0.01,
        )

        if short_option is None:
            return {
                "symbol": symbol,
                "error": f"Could not find short strike > LEAPS strike ${leaps_strike}",
            }

        # Calculate metrics — use effective_mid (falls back to lastPrice off-hours)
        leaps_mid = leaps_option["effective_mid"]
        leaps_bid = leaps_option.get("bid", 0) or 0
        leaps_ask = leaps_option.get("ask", 0) or 0
        if leaps_bid > 0 and leaps_ask > 0 and leaps_mid > 0:
            leaps_spread_pct = (leaps_ask - leaps_bid) / leaps_mid * 100
        else:
            leaps_spread_pct = 100  # unknown spread when using lastPrice

        short_mid = short_option["effective_mid"]
        short_bid = short_option.get("bid", 0) or 0
        short_ask = short_option.get("ask", 0) or 0
        if short_bid > 0 and short_ask > 0 and short_mid > 0:
            short_spread_pct = (short_ask - short_bid) / short_mid * 100
        else:
            short_spread_pct = 100  # unknown spread when using lastPrice

        leaps_intrinsic = max(0, current_price - leaps_strike)
        leaps_extrinsic = leaps_mid - leaps_intrinsic

        weekly_yield = (short_mid / leaps_mid * 100) if leaps_mid > 0 else 0
        annual_yield_est = weekly_yield * (365 / short_days) if short_days > 0 else 0

        remaining_T = (leaps_days - short_days) / 365
        leaps_value_at_short_expiry = black_scholes_price(
            S=short_strike, K=leaps_strike, T=remaining_T, r=0.05, sigma=avg_iv, option_type="call"
        )
        max_profit = leaps_value_at_short_expiry + short_mid - leaps_mid
        roi_pct = (max_profit / leaps_mid * 100) if leaps_mid > 0 else 0

        leaps_liquidity = _to_int(leaps_option.get("volume")) + _to_int(
            leaps_option.get("openInterest")
        )
        short_liquidity = _to_int(short_option.get("volume")) + _to_int(
            short_option.get("openInterest")
        )

        actual_leaps_delta = leaps_option.get("calculated_delta", 0)
        actual_short_delta = short_option.get("calculated_delta", 0)

        # Base score (options structure)
        base_score, base_breakdown = compute_base_score(
            actual_leaps_delta=actual_leaps_delta,
            actual_short_delta=actual_short_delta,
            leaps_liquidity=leaps_liquidity,
            short_liquidity=short_liquidity,
            leaps_spread_pct=leaps_spread_pct,
            short_spread_pct=short_spread_pct,
            avg_iv=avg_iv,
            annual_yield_est=annual_yield_est,
            leaps_delta_target=leaps_delta,
            short_delta_target=short_delta,
        )

        # Trend scoring
        hist = ticker.history(period="3mo")
        raw_indicators = compute_raw_indicators(hist)
        trend_delta, trend_breakdown = compute_trend_score(current_price, raw_indicators)

        # Earnings proximity scoring
        earnings_date_str = get_next_earnings_date(symbol)
        earnings_delta, earnings_breakdown = compute_earnings_score(earnings_date_str, short_days)

        score = base_score + trend_delta + earnings_delta

        score_breakdown = {
            **base_breakdown,
            "trend_delta": trend_delta,
            "trend": trend_breakdown,
            "earnings_delta": earnings_delta,
            "earnings": earnings_breakdown,
        }

        return {
            "symbol": symbol,
            "price": round(current_price, 2),
            "iv_pct": round(avg_iv * 100, 1),
            "pmcc_score": round(score, 1),
            "max_possible_score": 14,
            "leaps": {
                "expiry": leaps_expiry,
                "days": leaps_days,
                "strike": leaps_strike,
                "delta": round(actual_leaps_delta, 3),
                "bid": round(leaps_bid, 2),
                "ask": round(leaps_ask, 2),
                "mid": round(leaps_mid, 2),
                "intrinsic": round(leaps_intrinsic, 2),
                "extrinsic": round(leaps_extrinsic, 2),
                "spread_pct": round(leaps_spread_pct, 1),
                "volume": _to_int(leaps_option.get("volume")),
                "oi": _to_int(leaps_option.get("openInterest")),
            },
            "short": {
                "expiry": short_expiry,
                "days": short_days,
                "strike": short_strike,
                "delta": round(actual_short_delta, 3),
                "bid": round(short_bid, 2),
                "ask": round(short_ask, 2),
                "mid": round(short_mid, 2),
                "spread_pct": round(short_spread_pct, 1),
                "volume": _to_int(short_option.get("volume")),
                "oi": _to_int(short_option.get("openInterest")),
            },
            "metrics": {
                "net_debit": round(leaps_mid - short_mid, 2),
                "short_yield_pct": round(weekly_yield, 2),
                "annual_yield_est_pct": round(annual_yield_est, 1),
                "max_profit": round(max_profit, 2),
                "roi_pct": round(roi_pct, 1),
                "capital_required": round(leaps_mid * 100, 2),
            },
            "score_breakdown": score_breakdown,
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

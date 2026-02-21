# ABOUTME: Scans symbols for PMCC suitability based on option chain quality.
# ABOUTME: Scores on delta accuracy, liquidity, spread tightness, IV level, and yield.

from datetime import datetime

import pandas as pd
import yfinance as yf

from trading_skills.black_scholes import black_scholes_delta, black_scholes_price
from trading_skills.utils import get_current_price


def find_strike_by_delta(
    chain, current_price, target_delta, expiry_days, iv, r=0.05, min_strike=None, max_strike=None
):
    """Find strike closest to target delta with optional strike constraints."""
    T = expiry_days / 365
    best_strike = None
    best_delta_diff = float("inf")
    best_option = None

    for _, row in chain.iterrows():
        strike = row["strike"]

        if pd.isna(row.get("bid")) or row.get("bid", 0) <= 0:
            continue

        if min_strike is not None and strike < min_strike:
            continue
        if max_strike is not None and strike > max_strike:
            continue

        option_iv = row.get("impliedVolatility", iv)
        if pd.isna(option_iv) or option_iv <= 0:
            option_iv = iv

        delta = black_scholes_delta(current_price, strike, T, r, option_iv, "call")
        delta_diff = abs(delta - target_delta)

        if delta_diff < best_delta_diff:
            best_delta_diff = delta_diff
            best_strike = strike
            best_option = row.copy()
            best_option["calculated_delta"] = delta

    return best_strike, best_option


def analyze_pmcc(
    symbol: str,
    min_leaps_days: int = 270,
    short_days_range: tuple = (7, 21),
    leaps_delta: float = 0.80,
    short_delta: float = 0.20,
) -> dict | None:
    """Analyze a symbol for PMCC suitability."""
    try:
        ticker = yf.Ticker(symbol)
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

        # Estimate IV from ATM options
        atm_calls = leaps_chain.calls[
            (leaps_chain.calls["strike"] >= current_price * 0.95)
            & (leaps_chain.calls["strike"] <= current_price * 1.05)
        ]
        if not atm_calls.empty:
            avg_iv = atm_calls["impliedVolatility"].mean()
        else:
            avg_iv = 0.3

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

        # Calculate metrics
        leaps_mid = (leaps_option["bid"] + leaps_option["ask"]) / 2
        leaps_spread_pct = (
            (leaps_option["ask"] - leaps_option["bid"]) / leaps_mid * 100 if leaps_mid > 0 else 100
        )

        short_mid = (short_option["bid"] + short_option["ask"]) / 2
        short_spread_pct = (
            (short_option["ask"] - short_option["bid"]) / short_mid * 100 if short_mid > 0 else 100
        )

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

        leaps_liquidity = (leaps_option.get("volume", 0) or 0) + (
            leaps_option.get("openInterest", 0) or 0
        )
        short_liquidity = (short_option.get("volume", 0) or 0) + (
            short_option.get("openInterest", 0) or 0
        )

        # Calculate score
        score = 0

        actual_leaps_delta = leaps_option.get("calculated_delta", 0)
        actual_short_delta = short_option.get("calculated_delta", 0)

        if leaps_delta - 0.05 <= actual_leaps_delta <= leaps_delta + 0.05:
            score += 2
        elif leaps_delta - 0.10 <= actual_leaps_delta <= leaps_delta + 0.10:
            score += 1

        if short_delta - 0.05 <= actual_short_delta <= short_delta + 0.05:
            score += 1
        elif short_delta - 0.10 <= actual_short_delta <= short_delta + 0.10:
            score += 0.5

        if leaps_liquidity > 100:
            score += 1
        elif leaps_liquidity > 20:
            score += 0.5

        if short_liquidity > 500:
            score += 1
        elif short_liquidity > 100:
            score += 0.5

        if leaps_spread_pct < 5:
            score += 1
        elif leaps_spread_pct < 10:
            score += 0.5

        if short_spread_pct < 10:
            score += 1
        elif short_spread_pct < 20:
            score += 0.5

        if 0.25 <= avg_iv <= 0.50:
            score += 2
        elif 0.20 <= avg_iv <= 0.60:
            score += 1

        if annual_yield_est > 50:
            score += 2
        elif annual_yield_est > 30:
            score += 1
        elif annual_yield_est > 15:
            score += 0.5

        return {
            "symbol": symbol,
            "price": round(current_price, 2),
            "iv_pct": round(avg_iv * 100, 1),
            "pmcc_score": round(score, 1),
            "leaps": {
                "expiry": leaps_expiry,
                "days": leaps_days,
                "strike": leaps_strike,
                "delta": round(actual_leaps_delta, 3),
                "bid": round(leaps_option["bid"], 2),
                "ask": round(leaps_option["ask"], 2),
                "mid": round(leaps_mid, 2),
                "intrinsic": round(leaps_intrinsic, 2),
                "extrinsic": round(leaps_extrinsic, 2),
                "spread_pct": round(leaps_spread_pct, 1),
                "volume": int(leaps_option.get("volume", 0) or 0),
                "oi": int(leaps_option.get("openInterest", 0) or 0),
            },
            "short": {
                "expiry": short_expiry,
                "days": short_days,
                "strike": short_strike,
                "delta": round(actual_short_delta, 3),
                "bid": round(short_option["bid"], 2),
                "ask": round(short_option["ask"], 2),
                "mid": round(short_mid, 2),
                "spread_pct": round(short_spread_pct, 1),
                "volume": int(short_option.get("volume", 0) or 0),
                "oi": int(short_option.get("openInterest", 0) or 0),
            },
            "metrics": {
                "net_debit": round(leaps_mid - short_mid, 2),
                "short_yield_pct": round(weekly_yield, 2),
                "annual_yield_est_pct": round(annual_yield_est, 1),
                "max_profit": round(max_profit, 2),
                "roi_pct": round(roi_pct, 1),
                "capital_required": round(leaps_mid * 100, 2),
            },
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

# ABOUTME: Analyzes tactical collar strategies for PMCC positions.
# ABOUTME: Evaluates earnings risk and recommends optimal put protection.

import math
from datetime import datetime

import yfinance as yf

from trading_skills.black_scholes import black_scholes_price
from trading_skills.broker.connection import (
    CLIENT_IDS,
    fetch_positions,
    fetch_spot_prices,
    ib_connection,
    normalize_positions,
)
from trading_skills.earnings import get_next_earnings_date
from trading_skills.options import get_expiries
from trading_skills.utils import annualized_volatility


def get_earnings_date(symbol: str) -> tuple[datetime | None, str]:
    """Get next earnings date for a symbol as (datetime, timing_str)."""
    try:
        date_str = get_next_earnings_date(symbol)
        if date_str:
            return datetime.strptime(date_str, "%Y-%m-%d"), "after market close"
    except Exception:
        pass
    return None, ""


def get_stock_volatility(symbol: str, period: str = "3mo") -> dict:
    """Calculate stock's historical volatility and expected move."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        if hist.empty or len(hist) < 20:
            return {"error": "Insufficient data"}

        # Calculate volatility
        returns, daily_vol, annual_vol = annualized_volatility(hist["Close"])

        # Calculate expected moves for different time periods
        # Using 1 standard deviation move
        current_price = hist["Close"].iloc[-1]

        # Expected move over N days = price * daily_vol * sqrt(N)
        move_1_week = current_price * daily_vol * math.sqrt(5)
        move_2_weeks = current_price * daily_vol * math.sqrt(10)
        move_3_weeks = current_price * daily_vol * math.sqrt(15)

        # Volatility classification
        if annual_vol > 0.80:
            vol_class = "EXTREME"
        elif annual_vol > 0.60:
            vol_class = "VERY HIGH"
        elif annual_vol > 0.40:
            vol_class = "HIGH"
        elif annual_vol > 0.25:
            vol_class = "MODERATE"
        else:
            vol_class = "LOW"

        return {
            "current_price": current_price,
            "daily_vol": daily_vol,
            "annual_vol": annual_vol,
            "annual_vol_pct": annual_vol * 100,
            "move_1_week": move_1_week,
            "move_1_week_pct": (move_1_week / current_price) * 100,
            "move_2_weeks": move_2_weeks,
            "move_2_weeks_pct": (move_2_weeks / current_price) * 100,
            "move_3_weeks": move_3_weeks,
            "move_3_weeks_pct": (move_3_weeks / current_price) * 100,
            "vol_class": vol_class,
        }
    except Exception as e:
        return {"error": str(e)}


def get_put_chain(symbol: str, target_expiry: str) -> list[dict]:
    """Get put options for a specific expiry."""
    try:
        ticker = yf.Ticker(symbol)
        if target_expiry not in ticker.options:
            return []
        chain = ticker.option_chain(target_expiry)
        puts = chain.puts
        result = []
        for _, row in puts.iterrows():
            result.append(
                {
                    "strike": row["strike"],
                    "bid": row["bid"],
                    "ask": row["ask"],
                    "mid": (row["bid"] + row["ask"]) / 2,
                    "oi": row["openInterest"],
                    "iv": row.get("impliedVolatility", 0.4),
                }
            )
        return result
    except Exception:
        return []


get_available_expiries = get_expiries


def get_call_market_price(symbol: str, strike: float, expiry: str) -> float | None:
    """Get actual market price for a call option.

    Args:
        symbol: Stock symbol
        strike: Option strike price
        expiry: Expiry date in YYYYMMDD format (from IB) or YYYY-MM-DD format

    Returns:
        Mid price of the option, or None if not found
    """
    try:
        ticker = yf.Ticker(symbol)

        # Convert YYYYMMDD to YYYY-MM-DD if needed
        if len(expiry) == 8 and "-" not in expiry:
            expiry_formatted = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
        else:
            expiry_formatted = expiry

        # Get available expiries and find closest match
        available = ticker.options
        if expiry_formatted not in available:
            # Try to find the closest expiry
            target_date = datetime.strptime(expiry_formatted, "%Y-%m-%d")
            closest = None
            min_diff = float("inf")
            for exp in available:
                exp_date = datetime.strptime(exp, "%Y-%m-%d")
                diff = abs((exp_date - target_date).days)
                if diff < min_diff:
                    min_diff = diff
                    closest = exp
            if closest and min_diff <= 7:  # Within a week
                expiry_formatted = closest
            else:
                return None

        chain = ticker.option_chain(expiry_formatted)
        calls = chain.calls

        # Find the strike
        matching = calls[calls["strike"] == strike]
        if matching.empty:
            # Try to find closest strike
            if calls.empty:
                return None
            closest_idx = (calls["strike"] - strike).abs().idxmin()
            matching = calls.loc[[closest_idx]]
            if abs(matching.iloc[0]["strike"] - strike) > 5:  # More than $5 off
                return None

        row = matching.iloc[0]
        bid = row["bid"]
        ask = row["ask"]

        # Use mid price, or last price if bid/ask is zero
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        elif row.get("lastPrice", 0) > 0:
            return row["lastPrice"]

        return None
    except Exception as e:
        print(f"Warning: Could not fetch call price for {symbol} {strike} {expiry}: {e}")
        return None


def analyze_collar(
    symbol: str,
    current_price: float,
    long_strike: float,
    long_expiry: str,
    long_qty: int,
    long_cost: float,
    short_positions: list[dict],
    earnings_date: datetime | None,
) -> dict:
    """Analyze tactical collar strategy for the position."""
    today = datetime.now()

    # Get stock volatility for timing recommendations
    volatility = get_stock_volatility(symbol)

    # PMCC health check
    is_proper_pmcc = current_price >= long_strike * 0.95  # Within 5% of strike
    short_above_long = all(s["strike"] >= long_strike for s in short_positions)

    # Days to earnings
    days_to_earnings = (earnings_date - today).days if earnings_date else None

    # Get available expiries
    expiries = get_available_expiries(symbol)

    # Find suitable put expiries (after earnings if applicable)
    put_expiries = []
    if earnings_date and expiries:
        for exp in expiries:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_after_earnings = (exp_date - earnings_date).days
            days_from_now = (exp_date - today).days
            if 0 < days_after_earnings <= 60 and days_from_now > 0:
                put_expiries.append(
                    {
                        "expiry": exp,
                        "days_out": days_from_now,
                        "days_after_earnings": days_after_earnings,
                    }
                )
    elif expiries:
        # No earnings, just get near-term expiries
        for exp in expiries[:6]:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_from_now = (exp_date - today).days
            if days_from_now > 7:
                put_expiries.append(
                    {
                        "expiry": exp,
                        "days_out": days_from_now,
                        "days_after_earnings": None,
                    }
                )

    # Determine put strikes at various OTM levels (deduplicated)
    put_strike_5 = round(current_price * 0.95 / 5) * 5  # 5% OTM, round to 5
    put_strike_10 = round(current_price * 0.90 / 5) * 5  # 10% OTM
    put_strike_15 = round(current_price * 0.85 / 5) * 5  # 15% OTM
    # Deduplicate strikes (can happen when rounding)
    put_strikes = list(dict.fromkeys([put_strike_15, put_strike_10, put_strike_5]))

    # IV estimates
    iv_before = 0.50  # Elevated before earnings
    iv_after_up = 0.35  # Crushed after gap up
    iv_after_down = 0.45  # Stays elevated after gap down

    # Analyze each put expiry
    put_analysis = []
    for pe in put_expiries[:4]:  # Analyze up to 4 expiries
        T_before = pe["days_out"] / 365
        days_after = pe.get("days_after_earnings") or 7
        T_after = days_after / 365

        for put_strike in put_strikes:
            otm_pct = (current_price - put_strike) / current_price * 100

            # Get actual put price if available
            puts = get_put_chain(symbol, pe["expiry"])
            actual_put = next((p for p in puts if p["strike"] == put_strike), None)

            if actual_put:
                put_cost = actual_put["mid"]
            else:
                put_cost = black_scholes_price(
                    current_price, put_strike, T_before, 0.05, iv_before, "put"
                )

            total_cost = put_cost * long_qty * 100

            # Scenario analysis
            scenarios = {}

            # Gap up 10%
            price_up = current_price * 1.10
            put_value_up = black_scholes_price(
                price_up, put_strike, T_after, 0.05, iv_after_up, "put"
            )
            scenarios["gap_up_10"] = {
                "price": price_up,
                "put_value": put_value_up * long_qty * 100,
                "put_pnl": (put_value_up - put_cost) * long_qty * 100,
            }

            # Flat
            put_value_flat = black_scholes_price(
                current_price, put_strike, T_after, 0.05, 0.40, "put"
            )
            scenarios["flat"] = {
                "price": current_price,
                "put_value": put_value_flat * long_qty * 100,
                "put_pnl": (put_value_flat - put_cost) * long_qty * 100,
            }

            # Gap down 10%
            price_down = current_price * 0.90
            put_value_down = black_scholes_price(
                price_down, put_strike, T_after, 0.05, iv_after_down, "put"
            )
            put_value_down = max(put_value_down, put_strike - price_down)  # At least intrinsic
            scenarios["gap_down_10"] = {
                "price": price_down,
                "put_value": put_value_down * long_qty * 100,
                "put_pnl": (put_value_down - put_cost) * long_qty * 100,
            }

            # Gap down 15%
            price_down_15 = current_price * 0.85
            put_value_down_15 = black_scholes_price(
                price_down_15, put_strike, T_after, 0.05, iv_after_down, "put"
            )
            put_value_down_15 = max(put_value_down_15, put_strike - price_down_15)
            scenarios["gap_down_15"] = {
                "price": price_down_15,
                "put_value": put_value_down_15 * long_qty * 100,
                "put_pnl": (put_value_down_15 - put_cost) * long_qty * 100,
            }

            put_analysis.append(
                {
                    "expiry": pe["expiry"],
                    "days_out": pe["days_out"],
                    "days_after_earnings": pe.get("days_after_earnings"),
                    "strike": put_strike,
                    "otm_pct": otm_pct,
                    "cost_per_contract": put_cost,
                    "total_cost": total_cost,
                    "scenarios": scenarios,
                }
            )

    # Calculate long call risk without protection
    T_long = (datetime.strptime(long_expiry, "%Y%m%d") - today).days / 365

    # Try to get actual market price for the long call
    actual_long_price = get_call_market_price(symbol, long_strike, long_expiry)

    if actual_long_price:
        long_value_now = actual_long_price
        if current_price >= long_strike * 0.95:  # Near/ITM
            long_value_down_10 = max(0.1, long_value_now - (current_price * 0.10 * 0.55))
            long_value_down_15 = max(0.1, long_value_now - (current_price * 0.15 * 0.50))
            long_value_up_10 = long_value_now + (current_price * 0.10 * 0.60)
        else:  # OTM
            otm_ratio = current_price / long_strike
            long_value_down_10 = max(0.1, long_value_now * (0.70 * otm_ratio))
            long_value_down_15 = max(0.1, long_value_now * (0.55 * otm_ratio))
            long_value_up_10 = long_value_now + (current_price * 0.10 * 0.45)
    else:
        long_value_now = black_scholes_price(current_price, long_strike, T_long, 0.05, 0.60, "call")
        long_value_down_10 = black_scholes_price(
            current_price * 0.90, long_strike, T_long, 0.05, 0.65, "call"
        )
        long_value_down_15 = black_scholes_price(
            current_price * 0.85, long_strike, T_long, 0.05, 0.70, "call"
        )
        long_value_up_10 = black_scholes_price(
            current_price * 1.10, long_strike, T_long, 0.05, 0.50, "call"
        )

    unprotected_loss_10 = (long_value_now - long_value_down_10) * long_qty * 100
    unprotected_loss_15 = (long_value_now - long_value_down_15) * long_qty * 100
    unprotected_gain_10 = (long_value_up_10 - long_value_now) * long_qty * 100

    return {
        "symbol": symbol,
        "current_price": current_price,
        "long_strike": long_strike,
        "long_expiry": long_expiry,
        "long_qty": long_qty,
        "long_cost": long_cost,
        "long_value_now": long_value_now,
        "short_positions": short_positions,
        "is_proper_pmcc": is_proper_pmcc,
        "short_above_long": short_above_long,
        "earnings_date": earnings_date,
        "days_to_earnings": days_to_earnings,
        "put_analysis": put_analysis,
        "unprotected_loss_10": unprotected_loss_10,
        "unprotected_loss_15": unprotected_loss_15,
        "unprotected_gain_10": unprotected_gain_10,
        "volatility": volatility,
    }


async def find_collar_candidates(
    symbol: str,
    port: int = 7496,
    account: str | None = None,
) -> dict:
    """Fetch portfolio and run collar analysis for a PMCC position.

    Connects to IB, finds the long call (LEAPS) and short calls,
    fetches current price and earnings date, then runs collar analysis.
    """
    try:
        async with ib_connection(port, CLIENT_IDS["collar"]) as ib:
            managed = ib.managedAccounts()
            if account:
                if account not in managed:
                    return {"error": f"Account {account} not found. Available: {managed}"}
                accounts = [account]
            else:
                accounts = managed

            # Fetch and normalize positions
            raw = []
            for acct in accounts:
                raw.extend(await fetch_positions(ib, account=acct))
            positions = normalize_positions(raw)

            # Fetch underlying prices for option positions
            opt_symbols = {p["symbol"] for p in positions if p["sec_type"] == "OPT"}
            prices = await fetch_spot_prices(ib, list(opt_symbols))
            for pos in positions:
                if pos["symbol"] in prices:
                    pos["underlying_price"] = prices[pos["symbol"]]

    except ConnectionError as e:
        return {"error": str(e)}

    # Filter for the symbol
    symbol = symbol.upper()
    symbol_positions = [p for p in positions if p["symbol"] == symbol]

    if not symbol_positions:
        available = sorted(set(p["symbol"] for p in positions))
        return {"error": f"{symbol} not found in portfolio. Available: {available}"}

    # Separate long and short calls
    long_calls = [
        p for p in symbol_positions
        if p["sec_type"] == "OPT" and p["right"] == "C" and p["quantity"] > 0
    ]
    short_calls = [
        p for p in symbol_positions
        if p["sec_type"] == "OPT" and p["right"] == "C" and p["quantity"] < 0
    ]

    if not long_calls:
        return {"error": f"No long call positions found for {symbol}. Requires a PMCC position."}

    # Use the longest-dated long call as the LEAPS
    long_calls.sort(key=lambda x: x["expiry"], reverse=True)
    main_long = long_calls[0]

    # Get current price from IB data, fall back to yfinance
    current_price = main_long.get("underlying_price")
    if not current_price:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        current_price = info.get("regularMarketPrice") or info.get("previousClose")

    if not current_price:
        return {"error": f"Could not get current price for {symbol}"}

    # Get earnings date
    earnings_date, _ = get_earnings_date(symbol)

    # Format short positions
    short_positions = [
        {"strike": p["strike"], "expiry": p["expiry"], "qty": abs(p["quantity"])}
        for p in short_calls
    ]

    # Run analysis
    analysis = analyze_collar(
        symbol=symbol,
        current_price=current_price,
        long_strike=main_long["strike"],
        long_expiry=main_long["expiry"],
        long_qty=int(main_long["quantity"]),
        long_cost=main_long["avg_cost"],
        short_positions=short_positions,
        earnings_date=earnings_date,
    )

    # Serialize datetime for JSON
    if analysis.get("earnings_date"):
        analysis["earnings_date"] = analysis["earnings_date"].strftime("%Y-%m-%d")

    return analysis

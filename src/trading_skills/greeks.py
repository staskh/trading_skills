# ABOUTME: Calculates option Greeks using Black-Scholes model.
# ABOUTME: Computes IV from market price via Newton-Raphson.

from datetime import datetime

from trading_skills.black_scholes import black_scholes_greeks, implied_volatility


def calculate_greeks(
    spot: float,
    strike: float,
    option_type: str,
    expiry: str | None = None,
    dte: int | None = None,
    as_of_date: str | None = None,
    market_price: float | None = None,
    rate: float = 0.05,
    volatility: float | None = None,
) -> dict:
    """Calculate Greeks for a specific option.

    Args:
        spot: Current underlying price
        strike: Option strike price
        option_type: 'call' or 'put'
        expiry: Expiry date (YYYY-MM-DD) - use this OR dte
        dte: Days to expiration (alternative to expiry)
        as_of_date: Calculate as of this date instead of today (YYYY-MM-DD)
        market_price: Option market price (for IV calculation)
        rate: Risk-free rate
        volatility: Override volatility (if not calculating from market_price)
    """
    if dte is not None:
        days_to_expiry = dte
        expiry_str = f"{dte} DTE"
    elif expiry is not None:
        expiry_date = datetime.strptime(expiry, "%Y-%m-%d")
        if as_of_date:
            ref_date = datetime.strptime(as_of_date, "%Y-%m-%d")
        else:
            ref_date = datetime.now()
        days_to_expiry = (expiry_date - ref_date).days
        expiry_str = expiry
    else:
        return {"error": "Must provide either --expiry or --dte"}

    T = days_to_expiry / 365

    if T <= 0:
        return {"error": "Option has expired or expires today"}

    # Calculate IV from market price if provided
    if market_price is not None and market_price > 0:
        iv = implied_volatility(market_price, spot, strike, T, rate, option_type)
        if iv is None:
            iv = 0.30  # Fallback
    elif volatility is not None:
        iv = volatility
    else:
        iv = 0.30  # Default 30%

    greeks = black_scholes_greeks(spot, strike, T, rate, iv, option_type)

    return {
        "spot": round(spot, 2),
        "strike": strike,
        "expiry": expiry_str,
        "days_to_expiry": days_to_expiry,
        "option_type": option_type,
        "market_price": round(market_price, 2) if market_price else None,
        "iv": round(iv * 100, 2),
        "risk_free_rate": rate,
        "greeks": greeks,
    }

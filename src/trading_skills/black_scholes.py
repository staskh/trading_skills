# ABOUTME: Unified Black-Scholes option pricing and Greeks calculation.
# ABOUTME: Consolidates BS implementations from greeks, scanner, collar, and delta exposure modules.

import math

from scipy.stats import norm


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float) -> tuple[float, float]:
    """Calculate d1 and d2 for Black-Scholes formula."""
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return d1, d2


def black_scholes_price(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> float:
    """Calculate Black-Scholes option price.

    Args:
        S: Spot price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'
    """
    if T <= 0 or sigma <= 0:
        if option_type == "call":
            return max(0, S - K)
        return max(0, K - S)

    d1, d2 = _d1_d2(S, K, T, r, sigma)

    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def black_scholes_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Calculate vega (derivative of price w.r.t. sigma)."""
    if T <= 0 or sigma <= 0:
        return 0.0

    d1, _ = _d1_d2(S, K, T, r, sigma)
    return S * norm.pdf(d1) * math.sqrt(T)


def black_scholes_delta(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> float:
    """Calculate Black-Scholes delta.

    Args:
        S: Spot price
        K: Strike price
        T: Time to expiry in years
        r: Risk-free rate
        sigma: Volatility (annualized)
        option_type: 'call' or 'put'
    """
    if T <= 0 or sigma <= 0:
        if option_type == "call":
            return 1.0 if S > K else 0.0
        else:
            return -1.0 if S < K else 0.0

    d1, _ = _d1_d2(S, K, T, r, sigma)

    if option_type == "call":
        return norm.cdf(d1)
    else:
        return norm.cdf(d1) - 1.0


def black_scholes_greeks(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> dict:
    """Calculate all Black-Scholes Greeks."""
    if T <= 0:
        return {"error": "Option has expired"}

    if sigma <= 0:
        return {"error": "Invalid volatility"}

    d1, d2 = _d1_d2(S, K, T, r, sigma)
    sqrt_T = math.sqrt(T)

    N_d1 = norm.cdf(d1)
    N_d2 = norm.cdf(d2)
    n_d1 = norm.pdf(d1)

    if option_type == "call":
        delta = N_d1
        theta = (-S * n_d1 * sigma / (2 * sqrt_T) - r * K * math.exp(-r * T) * N_d2) / 365
        rho = K * T * math.exp(-r * T) * N_d2 / 100
        price = S * N_d1 - K * math.exp(-r * T) * N_d2
    else:
        delta = N_d1 - 1
        N_neg_d2 = norm.cdf(-d2)
        theta = (-S * n_d1 * sigma / (2 * sqrt_T) + r * K * math.exp(-r * T) * N_neg_d2) / 365
        rho = -K * T * math.exp(-r * T) * N_neg_d2 / 100
        price = K * math.exp(-r * T) * N_neg_d2 - S * (1 - N_d1)

    gamma = n_d1 / (S * sigma * sqrt_T)
    vega = S * n_d1 * sqrt_T / 100

    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


def implied_volatility(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> float | None:
    """Calculate implied volatility using Newton-Raphson with bisection fallback."""
    if market_price <= 0 or T <= 0:
        return None

    # Initial guess based on ATM approximation
    sigma = 0.3

    for _ in range(max_iterations):
        price = black_scholes_price(S, K, T, r, sigma, option_type)
        vega = black_scholes_vega(S, K, T, r, sigma)

        if vega < 1e-10:
            return _implied_volatility_bisection(market_price, S, K, T, r, option_type)

        diff = price - market_price
        if abs(diff) < tolerance:
            return sigma

        sigma = sigma - diff / vega

        if sigma <= 0.001:
            sigma = 0.001
        elif sigma > 5.0:
            sigma = 5.0

    return _implied_volatility_bisection(market_price, S, K, T, r, option_type)


def _implied_volatility_bisection(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> float | None:
    """Bisection method fallback for IV calculation."""
    low, high = 0.001, 5.0

    for _ in range(max_iterations):
        mid = (low + high) / 2
        price = black_scholes_price(S, K, T, r, mid, option_type)

        if abs(price - market_price) < tolerance:
            return mid

        if price > market_price:
            high = mid
        else:
            low = mid

    return (low + high) / 2


def estimate_iv(spot: float, strike: float, dte_years: float, option_type: str) -> float:
    """Estimate IV based on moneyness - rough approximation when market IV unavailable."""
    base_iv = 0.35
    moneyness = spot / strike

    if option_type == "call":
        if moneyness > 1.1:  # Deep ITM
            return base_iv * 0.8
        elif moneyness < 0.9:  # Deep OTM
            return base_iv * 1.3
    else:
        if moneyness < 0.9:  # Deep ITM put
            return base_iv * 0.8
        elif moneyness > 1.1:  # Deep OTM put
            return base_iv * 1.3

    return base_iv

# ABOUTME: Tests for unified Black-Scholes option pricing and Greeks.
# ABOUTME: Pure math tests with no external API dependencies.

import math

from trading_skills.black_scholes import (
    _implied_volatility_bisection,
    black_scholes_delta,
    black_scholes_greeks,
    black_scholes_price,
    black_scholes_vega,
    estimate_iv,
    implied_volatility,
)


class TestBlackScholesPrice:
    """Tests for BS option pricing."""

    def test_atm_call_reasonable(self):
        """ATM call with S=K=100, T=1, r=5%, vol=20%."""
        price = black_scholes_price(100, 100, 1.0, 0.05, 0.2, "call")
        assert 10 < price < 15

    def test_atm_put_reasonable(self):
        """ATM put pricing."""
        price = black_scholes_price(100, 100, 1.0, 0.05, 0.2, "put")
        assert 5 < price < 10

    def test_put_call_parity(self):
        """C - P = S - K*e^(-rT) (put-call parity)."""
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.3
        call = black_scholes_price(S, K, T, r, sigma, "call")
        put = black_scholes_price(S, K, T, r, sigma, "put")
        parity = S - K * math.exp(-r * T)
        assert abs((call - put) - parity) < 1e-6

    def test_deep_itm_call(self):
        """Deep ITM call approaches intrinsic value."""
        price = black_scholes_price(150, 100, 0.01, 0.05, 0.2, "call")
        assert price >= 49.9  # Close to intrinsic = 50

    def test_deep_otm_call(self):
        """Deep OTM call is near zero."""
        price = black_scholes_price(50, 100, 0.1, 0.05, 0.2, "call")
        assert price < 0.01

    def test_expired_call_intrinsic(self):
        """Expired option returns intrinsic value."""
        assert black_scholes_price(110, 100, 0, 0.05, 0.2, "call") == 10
        assert black_scholes_price(90, 100, 0, 0.05, 0.2, "call") == 0

    def test_expired_put_intrinsic(self):
        """Expired put returns intrinsic value."""
        assert black_scholes_price(90, 100, 0, 0.05, 0.2, "put") == 10
        assert black_scholes_price(110, 100, 0, 0.05, 0.2, "put") == 0

    def test_zero_volatility(self):
        """Zero vol returns intrinsic value."""
        assert black_scholes_price(110, 100, 1.0, 0.05, 0, "call") == 10
        assert black_scholes_price(90, 100, 1.0, 0.05, 0, "put") == 10


class TestBlackScholesDelta:
    """Tests for BS delta."""

    def test_atm_call_delta_near_half(self):
        delta = black_scholes_delta(100, 100, 1.0, 0.05, 0.2, "call")
        assert 0.45 < delta < 0.65

    def test_atm_put_delta_near_neg_half(self):
        delta = black_scholes_delta(100, 100, 1.0, 0.05, 0.2, "put")
        assert -0.55 < delta < -0.35

    def test_deep_itm_call_delta_near_one(self):
        delta = black_scholes_delta(200, 100, 1.0, 0.05, 0.2, "call")
        assert delta > 0.99

    def test_deep_otm_call_delta_near_zero(self):
        delta = black_scholes_delta(50, 100, 1.0, 0.05, 0.2, "call")
        assert delta < 0.01

    def test_call_delta_range(self):
        delta = black_scholes_delta(100, 100, 0.5, 0.05, 0.3, "call")
        assert 0 <= delta <= 1

    def test_put_delta_range(self):
        delta = black_scholes_delta(100, 100, 0.5, 0.05, 0.3, "put")
        assert -1 <= delta <= 0

    def test_expired_itm_call(self):
        assert black_scholes_delta(110, 100, 0, 0.05, 0.2, "call") == 1.0

    def test_expired_otm_call(self):
        assert black_scholes_delta(90, 100, 0, 0.05, 0.2, "call") == 0.0


class TestBlackScholesVega:
    """Tests for BS vega."""

    def test_atm_vega_positive(self):
        vega = black_scholes_vega(100, 100, 1.0, 0.05, 0.2)
        assert vega > 0

    def test_atm_has_highest_vega(self):
        """ATM option should have higher vega than OTM."""
        atm = black_scholes_vega(100, 100, 1.0, 0.05, 0.3)
        otm = black_scholes_vega(100, 130, 1.0, 0.05, 0.3)
        assert atm > otm

    def test_longer_expiry_higher_vega(self):
        short = black_scholes_vega(100, 100, 0.1, 0.05, 0.3)
        long = black_scholes_vega(100, 100, 1.0, 0.05, 0.3)
        assert long > short

    def test_expired_vega_zero(self):
        assert black_scholes_vega(100, 100, 0, 0.05, 0.2) == 0.0


class TestBlackScholesGreeks:
    """Tests for complete greeks calculation."""

    def test_returns_all_greeks(self):
        result = black_scholes_greeks(100, 100, 1.0, 0.05, 0.2, "call")
        for key in ["price", "delta", "gamma", "theta", "vega", "rho"]:
            assert key in result

    def test_call_greeks_signs(self):
        """Call: delta>0, gamma>0, theta<0, vega>0, rho>0."""
        g = black_scholes_greeks(100, 100, 0.5, 0.05, 0.3, "call")
        assert g["delta"] > 0
        assert g["gamma"] > 0
        assert g["theta"] < 0
        assert g["vega"] > 0
        assert g["rho"] > 0

    def test_put_greeks_signs(self):
        """Put: delta<0, gamma>0, theta<0, vega>0, rho<0."""
        g = black_scholes_greeks(100, 100, 0.5, 0.05, 0.3, "put")
        assert g["delta"] < 0
        assert g["gamma"] > 0
        assert g["theta"] < 0
        assert g["vega"] > 0
        assert g["rho"] < 0

    def test_expired_returns_error(self):
        result = black_scholes_greeks(100, 100, 0, 0.05, 0.2, "call")
        assert "error" in result

    def test_zero_vol_returns_error(self):
        result = black_scholes_greeks(100, 100, 1.0, 0.05, 0, "call")
        assert "error" in result


class TestImpliedVolatility:
    """Tests for IV calculation."""

    def test_roundtrip_call(self):
        """Price -> IV -> price should roundtrip."""
        sigma = 0.25
        price = black_scholes_price(100, 100, 0.5, 0.05, sigma, "call")
        iv = implied_volatility(price, 100, 100, 0.5, 0.05, "call")
        assert iv is not None
        assert abs(iv - sigma) < 0.001

    def test_roundtrip_put(self):
        sigma = 0.35
        price = black_scholes_price(100, 100, 0.5, 0.05, sigma, "put")
        iv = implied_volatility(price, 100, 100, 0.5, 0.05, "put")
        assert iv is not None
        assert abs(iv - sigma) < 0.001

    def test_zero_price_returns_none(self):
        assert implied_volatility(0, 100, 100, 0.5, 0.05, "call") is None

    def test_expired_returns_none(self):
        assert implied_volatility(5, 100, 100, 0, 0.05, "call") is None

    def test_high_iv(self):
        """High market price should give high IV."""
        price = black_scholes_price(100, 100, 0.5, 0.05, 1.5, "call")
        iv = implied_volatility(price, 100, 100, 0.5, 0.05, "call")
        assert iv is not None
        assert iv > 1.0


class TestBisectionFallback:
    """Tests for bisection fallback IV."""

    def test_converges(self):
        sigma = 0.30
        price = black_scholes_price(100, 100, 0.5, 0.05, sigma, "call")
        iv = _implied_volatility_bisection(price, 100, 100, 0.5, 0.05, "call")
        assert iv is not None
        assert abs(iv - sigma) < 0.01


class TestEstimateIV:
    """Tests for moneyness-based IV estimation."""

    def test_atm_returns_base(self):
        iv = estimate_iv(100, 100, 0.5, "call")
        assert iv == 0.35

    def test_deep_itm_call_lower_iv(self):
        iv = estimate_iv(120, 100, 0.5, "call")
        assert iv < 0.35

    def test_deep_otm_call_higher_iv(self):
        iv = estimate_iv(80, 100, 0.5, "call")
        assert iv > 0.35

    def test_deep_itm_put_lower_iv(self):
        iv = estimate_iv(80, 100, 0.5, "put")
        assert iv < 0.35

    def test_deep_otm_put_higher_iv(self):
        iv = estimate_iv(120, 100, 0.5, "put")
        assert iv > 0.35

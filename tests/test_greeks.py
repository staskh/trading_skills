# ABOUTME: Tests for option Greeks calculation module.
# ABOUTME: Tests calculate_greeks wrapper over Black-Scholes.


from trading_skills.greeks import calculate_greeks


class TestCalculateGreeksWithDTE:
    """Tests using DTE parameter."""

    def test_call_greeks(self):
        result = calculate_greeks(spot=230, strike=240, option_type="call", dte=30)
        assert result["option_type"] == "call"
        assert result["strike"] == 240
        assert "greeks" in result
        greeks = result["greeks"]
        assert 0 <= greeks["delta"] <= 1

    def test_put_greeks(self):
        result = calculate_greeks(spot=230, strike=220, option_type="put", dte=30)
        assert result["option_type"] == "put"
        greeks = result["greeks"]
        assert -1 <= greeks["delta"] <= 0

    def test_all_greek_fields_present(self):
        result = calculate_greeks(spot=100, strike=100, option_type="call", dte=30)
        greeks = result["greeks"]
        for field in ["delta", "gamma", "theta", "vega", "rho", "price"]:
            assert field in greeks

    def test_days_to_expiry_set(self):
        result = calculate_greeks(spot=100, strike=100, option_type="call", dte=45)
        assert result["days_to_expiry"] == 45


class TestCalculateGreeksWithExpiry:
    """Tests using expiry date parameter."""

    def test_with_future_expiry(self):
        result = calculate_greeks(spot=230, strike=235, option_type="call", expiry="2027-06-18")
        assert "greeks" in result
        assert result["days_to_expiry"] > 0

    def test_expired_option_returns_error(self):
        result = calculate_greeks(spot=230, strike=230, option_type="call", expiry="2020-01-01")
        assert "error" in result

    def test_as_of_date(self):
        """Calculate greeks as of a specific past date."""
        result = calculate_greeks(
            spot=230, strike=235, option_type="call", expiry="2027-06-18", as_of_date="2026-01-01"
        )
        assert "greeks" in result
        assert result["days_to_expiry"] > 500  # More than a year


class TestCalculateGreeksIV:
    """Tests for IV calculation from market price."""

    def test_iv_from_market_price(self):
        result = calculate_greeks(
            spot=230, strike=235, option_type="call", dte=30, market_price=5.50
        )
        assert result["iv"] > 0
        assert result["market_price"] == 5.50

    def test_custom_volatility(self):
        result = calculate_greeks(spot=230, strike=235, option_type="call", dte=30, volatility=0.40)
        assert result["iv"] == 40.0  # 0.40 * 100

    def test_default_volatility(self):
        result = calculate_greeks(spot=230, strike=235, option_type="call", dte=30)
        assert result["iv"] == 30.0  # Default 0.30 * 100


class TestCalculateGreeksErrors:
    """Tests for error handling."""

    def test_no_expiry_or_dte(self):
        result = calculate_greeks(spot=100, strike=100, option_type="call")
        assert "error" in result

    def test_zero_dte_returns_error(self):
        result = calculate_greeks(spot=100, strike=100, option_type="call", dte=0)
        assert "error" in result

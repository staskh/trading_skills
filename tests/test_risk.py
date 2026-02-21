# ABOUTME: Tests for risk assessment module using real Yahoo Finance data.
# ABOUTME: Validates volatility, beta, VaR, drawdown, and Sharpe calculations.


from trading_skills.risk import calculate_risk_metrics


class TestCalculateRiskMetrics:
    """Tests for risk metrics calculation."""

    def test_basic_structure(self):
        result = calculate_risk_metrics("AAPL", period="3mo")
        assert result["symbol"] == "AAPL"
        assert "volatility" in result
        assert "var" in result

    def test_volatility_fields(self):
        result = calculate_risk_metrics("AAPL", period="3mo")
        vol = result["volatility"]
        assert "daily" in vol
        assert "annual" in vol
        assert vol["annual"] > vol["daily"]

    def test_var_fields(self):
        result = calculate_risk_metrics("AAPL", period="3mo")
        var = result["var"]
        assert "var_95_daily" in var
        assert "var_99_daily" in var
        # 99% VaR should be more negative than 95%
        assert var["var_99_daily"] < var["var_95_daily"]

    def test_beta(self):
        result = calculate_risk_metrics("AAPL", period="1y")
        assert "beta" in result
        if result["beta"] is not None:
            assert -5 < result["beta"] < 5

    def test_max_drawdown(self):
        result = calculate_risk_metrics("AAPL", period="1y")
        assert "max_drawdown" in result
        assert result["max_drawdown"] <= 0

    def test_sharpe_ratio(self):
        result = calculate_risk_metrics("AAPL", period="1y")
        assert "sharpe_ratio" in result

    def test_position_size(self):
        result = calculate_risk_metrics("AAPL", period="3mo", position_size=10000)
        assert "position" in result
        pos = result["position"]
        assert pos["size"] == 10000
        assert "shares" in pos
        assert "var_95_dollar" in pos
        assert "var_99_dollar" in pos
        assert pos["shares"] > 0

    def test_return_fields(self):
        result = calculate_risk_metrics("AAPL", period="3mo")
        assert "return" in result
        assert "mean_daily" in result["return"]
        assert "total_period" in result["return"]

    def test_invalid_symbol(self):
        result = calculate_risk_metrics("INVALIDXYZ123")
        assert "error" in result

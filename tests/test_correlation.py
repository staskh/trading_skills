# ABOUTME: Tests for correlation analysis module using real Yahoo Finance data.
# ABOUTME: Validates matrix computation, symmetry, and value ranges.


from trading_skills.correlation import compute_correlation


class TestComputeCorrelation:
    """Tests for correlation matrix computation."""

    def test_two_symbols(self):
        result = compute_correlation(["AAPL", "MSFT"], period="3mo")
        assert "correlation_matrix" in result
        assert "AAPL" in result["correlation_matrix"]
        assert "MSFT" in result["correlation_matrix"]["AAPL"]

    def test_values_in_range(self):
        result = compute_correlation(["AAPL", "MSFT", "GOOGL"], period="3mo")
        for sym1, correlations in result["correlation_matrix"].items():
            for sym2, value in correlations.items():
                assert -1 <= value <= 1, f"{sym1}-{sym2} out of range: {value}"

    def test_diagonal_is_one(self):
        result = compute_correlation(["AAPL", "MSFT"], period="3mo")
        assert result["correlation_matrix"]["AAPL"]["AAPL"] == 1.0
        assert result["correlation_matrix"]["MSFT"]["MSFT"] == 1.0

    def test_symmetric(self):
        result = compute_correlation(["AAPL", "MSFT", "GOOGL"], period="3mo")
        matrix = result["correlation_matrix"]
        for sym1 in matrix:
            for sym2 in matrix[sym1]:
                assert abs(matrix[sym1][sym2] - matrix[sym2][sym1]) < 0.001

    def test_metadata(self):
        result = compute_correlation(["AAPL", "MSFT"], period="6mo")
        assert "symbols" in result
        assert "period" in result
        assert result["period"] == "6mo"

    def test_single_symbol_error(self):
        result = compute_correlation(["AAPL"])
        assert "error" in result

    def test_empty_list_error(self):
        result = compute_correlation([])
        assert "error" in result

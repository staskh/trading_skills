# ABOUTME: Tests for Piotroski F-Score calculation using real Yahoo Finance data.
# ABOUTME: Validates score range, criteria breakdown, and interpretation.


from trading_skills.piotroski import calculate_piotroski_score


class TestCalculatePiotroskiScore:
    """Tests with real Yahoo Finance data."""

    def test_valid_symbol(self):
        result = calculate_piotroski_score("AAPL")
        assert result["symbol"] == "AAPL"
        assert "score" in result
        assert "max_score" in result
        assert result["max_score"] == 9

    def test_score_range(self):
        result = calculate_piotroski_score("MSFT")
        assert 0 <= result["score"] <= 9

    def test_nine_criteria(self):
        result = calculate_piotroski_score("AAPL")
        assert "criteria" in result
        assert len(result["criteria"]) == 9

    def test_criteria_structure(self):
        result = calculate_piotroski_score("AAPL")
        for key, crit in result["criteria"].items():
            assert "passed" in crit
            assert "description" in crit
            assert isinstance(crit["passed"], bool)

    def test_interpretation(self):
        result = calculate_piotroski_score("AAPL")
        assert "interpretation" in result
        valid = [
            "Excellent - Very strong financial health",
            "Good - Strong financial health",
            "Fair - Moderate financial health",
            "Poor - Weak financial health",
        ]
        assert result["interpretation"] in valid

    def test_score_matches_criteria(self):
        """Score equals number of passed criteria."""
        result = calculate_piotroski_score("AAPL")
        passed_count = sum(1 for c in result["criteria"].values() if c["passed"])
        assert result["score"] == passed_count

    def test_invalid_symbol(self):
        result = calculate_piotroski_score("INVALIDXYZ123")
        assert "error" in result

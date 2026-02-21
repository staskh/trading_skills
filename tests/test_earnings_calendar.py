#!/usr/bin/env python3
# ABOUTME: Tests for earnings calendar skill.
# ABOUTME: Validates earnings date retrieval for single and multiple symbols.

import json
import subprocess
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent.parent / ".claude/skills/earnings-calendar/scripts/earnings.py"


def run_earnings(*args) -> dict:
    """Run earnings.py and return parsed JSON output."""
    cmd = ["uv", "run", "python", str(SCRIPT_PATH)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Script failed: {result.stderr}")
    return json.loads(result.stdout)


class TestSingleSymbol:
    """Tests for single symbol earnings lookup."""

    def test_returns_dict_with_symbol(self):
        """Single symbol returns dict with symbol field."""
        result = run_earnings("AAPL")
        assert isinstance(result, dict)
        assert result["symbol"] == "AAPL"

    def test_contains_earnings_date(self):
        """Result contains earnings_date field."""
        result = run_earnings("AAPL")
        assert "earnings_date" in result

    def test_contains_timing(self):
        """Result contains timing field (before/after market)."""
        result = run_earnings("AAPL")
        # timing can be "BMO", "AMC", or null if unknown
        assert "timing" in result

    def test_contains_eps_estimate(self):
        """Result contains eps_estimate field."""
        result = run_earnings("AAPL")
        assert "eps_estimate" in result

    def test_invalid_symbol_returns_error(self):
        """Invalid symbol returns error field."""
        result = run_earnings("INVALIDXYZ123")
        assert "error" in result


class TestMultipleSymbols:
    """Tests for multiple symbol earnings lookup."""

    def test_multiple_symbols_returns_results_array(self):
        """Multiple symbols return results array."""
        result = run_earnings("AAPL,MSFT,GOOGL")
        assert "results" in result
        assert isinstance(result["results"], list)
        assert len(result["results"]) == 3

    def test_each_result_has_required_fields(self):
        """Each result in array has required fields."""
        result = run_earnings("AAPL,MSFT")
        for r in result["results"]:
            assert "symbol" in r
            assert "earnings_date" in r
            assert "timing" in r
            assert "eps_estimate" in r

    def test_results_sorted_by_date(self):
        """Results are sorted by earnings date (soonest first)."""
        result = run_earnings("AAPL,MSFT,GOOGL,NVDA")
        dates = []
        for r in result["results"]:
            if r.get("earnings_date"):
                dates.append(r["earnings_date"])
        # Check dates are in ascending order
        assert dates == sorted(dates)


class TestOutputFormat:
    """Tests for output format details."""

    def test_date_format_iso(self):
        """Earnings date is in ISO format (YYYY-MM-DD)."""
        result = run_earnings("AAPL")
        if result.get("earnings_date"):
            date = result["earnings_date"]
            # Should match YYYY-MM-DD pattern
            assert len(date) == 10
            assert date[4] == "-" and date[7] == "-"

    def test_timing_values(self):
        """Timing is one of expected values or null."""
        result = run_earnings("AAPL")
        timing = result.get("timing")
        assert timing in ["BMO", "AMC", None]

    def test_eps_estimate_is_number_or_null(self):
        """EPS estimate is a number or null."""
        result = run_earnings("AAPL")
        eps = result.get("eps_estimate")
        assert eps is None or isinstance(eps, (int, float))

# ABOUTME: Tests for the intraday_technicals.py skill script.
# ABOUTME: Feeds synthetic intraday bars to build_result; no network.

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

SKILL_DIR = Path(__file__).parent.parent / ".claude/skills/technical-analysis"
SCRIPT = SKILL_DIR / "scripts/intraday_technicals.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("intraday_technicals", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_script()
build_result = _mod.build_result


def make_bars(closes) -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    index = pd.date_range(
        "2026-11-04 09:30", periods=len(closes), freq="5min", tz="America/New_York"
    )
    return pd.DataFrame(
        {
            "Open": closes,
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": np.full(len(closes), 1000),
        },
        index=index,
    )


def v_shape(n_down: int, n_up: int) -> list[float]:
    """Falling then rising closes — produces an upward EMA9/EMA21 crossover near the end."""
    down = np.linspace(110, 100, n_down)
    up = np.linspace(100, 112, n_up)
    return list(down) + list(up)


class TestBuildResult:
    def test_price_change_from_first_bar(self):
        result = build_result("TEST", "5m", "1d", make_bars([100, 101, 102, 105]))
        assert result["price"] == {"current": 105.0, "change": 5.0, "change_pct": 5.0}

    def test_few_bars_warns(self):
        result = build_result("TEST", "5m", "1d", make_bars(np.linspace(100, 101, 10)))
        assert result["bars"] == 10
        assert result["warnings"]

    def test_enough_bars_no_warnings(self):
        result = build_result("TEST", "5m", "1d", make_bars(v_shape(40, 20)))
        assert result["warnings"] == []
        assert result["indicators"]["rsi"] is not None

    def test_crossover_age_in_bars_and_minutes(self):
        result = build_result("TEST", "5m", "1d", make_bars(v_shape(40, 20)))
        cross = result["indicators"]["ema"]["crossover"]
        assert cross["direction"] == "up"
        assert "days_ago" not in cross
        assert cross["minutes_ago"] == cross["bars_ago"] * 5

    def test_crossover_minutes_scale_with_interval(self):
        bars = make_bars(v_shape(40, 20))
        five = build_result("TEST", "5m", "1d", bars)["indicators"]["ema"]["crossover"]
        fifteen = build_result("TEST", "15m", "5d", bars)["indicators"]["ema"]["crossover"]
        assert fifteen["minutes_ago"] == five["bars_ago"] * 15

    def test_empty_frame_returns_error(self):
        result = build_result("TEST", "5m", "1d", make_bars([]))
        assert result["bars"] == 0
        assert "error" in result

    def test_nan_closes_dropped(self):
        result = build_result("TEST", "5m", "1d", make_bars([100, np.nan, 102]))
        assert result["bars"] == 2

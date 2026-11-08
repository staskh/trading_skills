# ABOUTME: Tests for the daily candle chart with EMA crossovers and RSI.
# ABOUTME: Crossover detection uses synthetic series; the live test renders a real JPG.

import pandas as pd
import pytest

from trading_skills.chart_ema_rsi import ema_crossovers, render_chart


def _series(values):
    return pd.Series(values, index=pd.bdate_range("2026-10-01", periods=len(values)), dtype=float)


def test_ema_crossovers_marks_golden_and_death():
    fast = _series([1, 2, 4, 3, 1, 2])
    slow = _series([2, 2, 3, 3, 2, 1])
    crosses = ema_crossovers(fast, slow)
    assert [(c["date"], c["type"]) for c in crosses] == [
        ("2026-10-05", "golden"),
        ("2026-10-07", "death"),
        ("2026-10-08", "golden"),
    ]


def test_ema_crossovers_touch_then_separate_counts_once():
    """Equal values are not a side; the cross is dated when the fast line clears the slow."""
    fast = _series([1, 2, 3])
    slow = _series([2, 2, 2])
    assert [(c["date"], c["type"]) for c in ema_crossovers(fast, slow)] == [
        ("2026-10-05", "golden")
    ]


def test_ema_crossovers_ignore_warmup_nans():
    fast = _series([None, None, 1, 3])
    slow = _series([None, 2, 2, 2])
    assert [c["type"] for c in ema_crossovers(fast, slow)] == ["golden"]


def test_ema_crossovers_none_when_lines_never_cross():
    assert ema_crossovers(_series([3, 4, 5]), _series([1, 2, 3])) == []


def test_render_chart_live(tmp_path):
    out = tmp_path / "aapl.jpg"
    result = render_chart("aapl", period="6mo", output=out)
    assert result["symbol"] == "AAPL"
    assert result["path"] == str(out)
    assert out.read_bytes()[:3] == b"\xff\xd8\xff"  # JPEG magic
    assert result["data_delay"] == "15min"
    assert "generated_at" in result
    assert 0 <= result["rsi"] <= 100
    assert result["ema_fast"] > 0 and result["ema_slow"] > 0
    assert result["trend"] in {"bullish", "bearish"}
    for c in result["crossovers"]:
        assert c["type"] in {"golden", "death"}


def test_render_chart_unknown_symbol(tmp_path):
    result = render_chart("ZZZZNOTREAL", output=tmp_path / "x.jpg")
    assert "error" in result
    assert not (tmp_path / "x.jpg").exists()


@pytest.mark.parametrize("fast,slow", [(20, 9), (9, 9)])
def test_render_chart_rejects_bad_ema_lengths(tmp_path, fast, slow):
    with pytest.raises(ValueError):
        render_chart("AAPL", fast=fast, slow=slow, output=tmp_path / "x.jpg")

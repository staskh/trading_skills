# ABOUTME: Tests for market regime classification from SPY/QQQ trend and VIX term structure.
# ABOUTME: Pure-logic table tests on constructed inputs plus one live fetch.

from trading_skills.market import classify_regime, market_regime


def idx(price, sma50, sma200):
    return {
        "price": {"current": price},
        "indicators": {"sma200": {"sma50": sma50, "sma200": sma200}},
    }


BULL = idx(500, 480, 450)
BEAR = idx(400, 420, 450)


def test_risk_off_when_spy_and_qqq_below_sma200():
    r = classify_regime(BEAR, BEAR, 15, 18)
    assert r["regime"] == "risk_off"


def test_risk_off_on_high_vix_and_backwardation():
    r = classify_regime(BULL, BULL, 27, 24)
    assert r["regime"] == "risk_off"


def test_risk_on_when_all_conditions_hold():
    r = classify_regime(BULL, BULL, 15, 18)
    assert r["regime"] == "risk_on"


def test_neutral_when_mixed():
    r = classify_regime(BULL, BULL, 22, 24)
    assert r["regime"] == "neutral"


def test_single_risk_off_condition_is_neutral():
    r = classify_regime(BEAR, BULL, 15, 18)
    assert r["regime"] == "neutral"


def test_missing_vix_is_neutral_with_reason():
    r = classify_regime(BULL, BULL, None, 18)
    assert r["regime"] == "neutral"
    assert "VIX unavailable" in r["reasons"]


def test_error_result_is_unavailable():
    r = classify_regime({"error": "x"}, BULL, 15, 18)
    assert r["regime"] == "neutral"
    assert "SPY SMA200 unavailable" in r["reasons"]


def test_sma50_falls_back_to_sma_group():
    spy = {"price": {"current": 500}, "indicators": {"sma": {"sma50": 480}}}
    r = classify_regime(spy, BULL, 15, 18)
    assert "SPY SMA50 unavailable" not in r["reasons"]
    assert "SPY SMA200 unavailable" in r["reasons"]


def test_market_regime_live():
    r = market_regime()
    assert r["regime"] in ("risk_on", "neutral", "risk_off")
    assert r["data_delay"] == "15min"
    assert "generated_at" in r

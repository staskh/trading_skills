# ABOUTME: Market regime (risk_on, neutral, risk_off) from SPY and QQQ trend and VIX term structure.
# ABOUTME: classify_regime is pure; market_regime fetches the inputs and classifies them.

from trading_skills.quote import get_quote
from trading_skills.technicals import compute_indicators
from trading_skills.utils import generated_at_str

RISK_OFF_VIX = 25
RISK_ON_VIX = 20
RISK_OFF_MIN_CONDITIONS = 2


def _price(result: dict) -> float | None:
    return (result.get("price") or {}).get("current")


def _sma(result: dict, name: str) -> float | None:
    indicators = result.get("indicators") or {}
    if name == "sma200":
        return (indicators.get("sma200") or {}).get("sma200")
    value = (indicators.get("sma200") or {}).get("sma50")
    if value is None:
        value = (indicators.get("sma") or {}).get("sma50")
    return value


def _compare(label: str, left, right, op, reasons: list[str]) -> bool:
    """Evaluate op(left, right); a missing operand is false and recorded as unavailable."""
    if left is None or right is None:
        reasons.append(f"{label} unavailable")
        return False
    return op(left, right)


def classify_regime(spy: dict, qqq: dict, vix: float | None, vix3m: float | None) -> dict:
    """Classify the market regime from SPY/QQQ indicator results and VIX levels.

    risk_off: at least 2 of SPY < SMA200, QQQ < SMA200, VIX >= 25, VIX > VIX3M.
    risk_on: SPY > SMA50, QQQ > SMA50, VIX < 20 and VIX < VIX3M all hold.
    Otherwise neutral. A missing input makes its condition false.
    """
    reasons: list[str] = []
    off_flags = {
        "SPY below SMA200": _compare(
            "SPY SMA200", _price(spy), _sma(spy, "sma200"), lambda a, b: a < b, reasons
        ),
        "QQQ below SMA200": _compare(
            "QQQ SMA200", _price(qqq), _sma(qqq, "sma200"), lambda a, b: a < b, reasons
        ),
        f"VIX >= {RISK_OFF_VIX}": _compare(
            "VIX", vix, RISK_OFF_VIX if vix is not None else None, lambda a, b: a >= b, reasons
        ),
        "VIX above VIX3M (backwardation)": _compare(
            "VIX/VIX3M", vix, vix3m, lambda a, b: a > b, reasons
        ),
    }
    on_flags = {
        "SPY above SMA50": _compare(
            "SPY SMA50", _price(spy), _sma(spy, "sma50"), lambda a, b: a > b, reasons
        ),
        "QQQ above SMA50": _compare(
            "QQQ SMA50", _price(qqq), _sma(qqq, "sma50"), lambda a, b: a > b, reasons
        ),
        f"VIX < {RISK_ON_VIX}": _compare(
            "VIX", vix, RISK_ON_VIX if vix is not None else None, lambda a, b: a < b, reasons
        ),
        "VIX below VIX3M": _compare("VIX/VIX3M", vix, vix3m, lambda a, b: a < b, reasons),
    }

    triggered_off = [name for name, hit in off_flags.items() if hit]
    if len(triggered_off) >= RISK_OFF_MIN_CONDITIONS:
        regime = "risk_off"
        met = triggered_off
    elif all(on_flags.values()):
        regime = "risk_on"
        met = list(on_flags)
    else:
        regime = "neutral"
        met = []
    reasons = met + list(dict.fromkeys(reasons))
    return {"regime": regime, "reasons": reasons}


def _quote_price(symbol: str) -> float | None:
    quote = get_quote(symbol)
    return None if "error" in quote else quote.get("price")


def market_regime() -> dict:
    """Fetch SPY, QQQ, VIX and VIX3M and classify the current market regime."""
    spy = compute_indicators("SPY", period="2y", indicators=["sma", "sma200"])
    qqq = compute_indicators("QQQ", period="2y", indicators=["sma", "sma200"])
    vix = _quote_price("^VIX")
    vix3m = _quote_price("^VIX3M")
    return {
        **classify_regime(spy, qqq, vix, vix3m),
        "spy": spy,
        "qqq": qqq,
        "vix": vix,
        "vix3m": vix3m,
        "generated_at": generated_at_str(),
        "data_delay": "15min",
    }

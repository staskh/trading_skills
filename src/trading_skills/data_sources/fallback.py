# ABOUTME: Fallback chain that resolves earnings data when the primary (yfinance) is unavailable.
# ABOUTME: Next date: yfinance -> NASDAQ -> estimate from SEC cadence; past dates: yfinance -> SEC.

import statistics
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from trading_skills.data_sources import nasdaq, sec_edgar

_NY = ZoneInfo("America/New_York")

# Plausible quarterly reporting gap (days) when estimating the next date.
_MIN_GAP, _MAX_GAP = 60, 130


def _to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            continue
    return None


def _estimate_next_from_dates(dates, today: date | None = None) -> str | None:
    """Project the next earnings date from the cadence of historical dates."""
    today = today or datetime.now(_NY).date()
    parsed = sorted({d for d in (_to_date(x) for x in dates) if d}, reverse=True)
    if len(parsed) < 2:
        return None
    gaps = [(parsed[i] - parsed[i + 1]).days for i in range(len(parsed) - 1)]
    gaps = [g for g in gaps if _MIN_GAP <= g <= _MAX_GAP]
    if not gaps:
        return None
    step = int(statistics.median(gaps))
    most_recent = parsed[0]
    # If the latest known report is already stale (older than ~2 cadence steps),
    # the cadence is no longer trustworthy — don't fabricate a far-future date
    # for a delisted/dormant name.
    if most_recent < today - timedelta(days=2 * step):
        return None
    nxt = most_recent
    while nxt <= today:
        nxt = nxt + timedelta(days=step)
    return nxt.isoformat()


def resolve_next_earnings_date(symbol: str, yf_value=None, today: date | None = None) -> dict:
    """Resolve the next earnings date through the fallback chain.

    Returns {"date": "YYYY-MM-DD"|None, "source": "yfinance"|"nasdaq"|"sec_estimate"|None}.
    `yf_value` is the caller's already-fetched yfinance result (used as primary).
    """
    today = today or datetime.now(_NY).date()
    if yf_value:
        return {"date": str(yf_value)[:10], "source": "yfinance"}

    # NASDAQ's date is regex-scraped from free text; only trust it if it is
    # genuinely in the future (guards against a "last reported" date leaking in).
    d = nasdaq.get_next_earnings_date(symbol)
    d_parsed = _to_date(d)
    if d_parsed and d_parsed > today:
        return {"date": d, "source": "nasdaq"}

    est = _estimate_next_from_dates(
        sec_edgar.get_earnings_release_dates(symbol, limit=8), today=today
    )
    if est:
        return {"date": est, "source": "sec_estimate"}

    return {"date": None, "source": None}


def resolve_past_earnings_dates(symbol: str, yf_dates=None, limit: int = 12) -> list[str]:
    """Resolve historical earnings-release dates: yfinance result if given, else SEC."""
    if yf_dates:
        return [str(d)[:10] for d in yf_dates]
    return sec_edgar.get_earnings_release_dates(symbol, limit=limit)


def resolve_earnings_surprises(symbol: str) -> list[dict]:
    """EPS estimate/actual/surprise history from NASDAQ (for the surprise-streak factor)."""
    return nasdaq.get_earnings_surprise(symbol)

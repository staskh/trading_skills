# ABOUTME: NASDAQ API client — EPS estimate/actual/surprise history and best-effort next date.
# ABOUTME: Undocumented endpoints; requires a browser User-Agent. Used as a secondary source.

import re
from datetime import datetime

from trading_skills.data_sources._http import get_json

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"}
_SURPRISE_URL = "https://api.nasdaq.com/api/company/{symbol}/earnings-surprise"
_EARNINGS_DATE_URL = "https://api.nasdaq.com/api/analyst/{symbol}/earnings-date"

_DATE_RE = re.compile(r"([A-Z][a-z]{2,8} \d{1,2}, \d{4})")


def _to_float(v):
    if v is None:
        return None
    s = str(v).replace("$", "").replace(",", "").replace("%", "").strip()
    # Accounting parentheses denote negatives, e.g. "($0.12)" -> -0.12. Without
    # this, every loss/negative-surprise quarter would silently become None.
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_surprise(data) -> list[dict]:
    """Normalize the earnings-surprise table into est/actual/surprise rows."""
    rows = ((data or {}).get("data") or {}).get("earningsSurpriseTable") or {}
    rows = rows.get("rows") or [] if isinstance(rows, dict) else []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append(
            {
                "fiscal_quarter_end": r.get("fiscalQtrEnd"),
                "date_reported": r.get("dateReported"),
                "eps_actual": _to_float(r.get("eps")),
                "eps_estimate": _to_float(r.get("consensusForecast")),
                "surprise_pct": _to_float(r.get("percentageSurprise")),
            }
        )
    return out


def get_earnings_surprise(symbol: str) -> list[dict]:
    """EPS estimate/actual/surprise for recent quarters (newest first), or []."""
    data = get_json(_SURPRISE_URL.format(symbol=symbol.upper()), headers=_HEADERS)
    return _parse_surprise(data)


def _parse_next_date(data) -> str | None:
    """Best-effort next-earnings date from the analyst endpoint text.

    The endpoint frequently returns a 'vendor hasn't provided' message with no
    date, in which case this returns None and the caller should fall through.
    """
    d = (data or {}).get("data") or {}
    text = " ".join(str(d.get(k, "")) for k in ("announcement", "reportText"))
    m = _DATE_RE.search(text)
    if not m:
        return None
    # NASDAQ uses the 4-letter "Sept" for September, which neither %b ("Sep")
    # nor %B ("September") parses; normalize it first.
    token = re.sub(r"\bSept\b", "Sep", m.group(1))
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(token, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def get_next_earnings_date(symbol: str) -> str | None:
    """Best-effort upcoming earnings date (YYYY-MM-DD), or None."""
    data = get_json(_EARNINGS_DATE_URL.format(symbol=symbol.upper()), headers=_HEADERS)
    return _parse_next_date(data)

# ABOUTME: SEC EDGAR client — official ticker->CIK map and 8-K earnings-release dates.
# ABOUTME: Free, no key; SEC fair-use requires a descriptive User-Agent with contact.

import os

from trading_skills.data_sources._http import get_json

# SEC's fair-access policy requires a User-Agent that includes a contact EMAIL;
# www.sec.gov returns 403 without one. The default uses the IANA-reserved
# example.com as an honest placeholder — set TRADING_SKILLS_SEC_UA to your own
# "name your-real@email" in any real deployment to honor the policy.
_DEFAULT_UA = "trading_skills/0.8 (contact@example.com)"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# 8-K "Item 2.02 — Results of Operations and Financial Condition" is the earnings
# release. Other 8-K items (5.02 officer changes, etc.) are not earnings.
_EARNINGS_ITEM = "2.02"


def _ua() -> str:
    return os.environ.get("TRADING_SKILLS_SEC_UA", _DEFAULT_UA)


def _headers() -> dict:
    return {"User-Agent": _ua(), "Accept-Encoding": "gzip, deflate"}


def _parse_cik_map(tickers_json, symbol: str) -> str | None:
    """Find the zero-padded 10-digit CIK for a ticker in company_tickers.json."""
    if not isinstance(tickers_json, dict):
        return None
    # SEC writes dual-class tickers with a hyphen (e.g. BRK-B); callers may pass
    # a dot (BRK.B). Normalize both sides so either form resolves.
    sym = symbol.upper().replace(".", "-")
    for row in tickers_json.values():
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker", "")).upper().replace(".", "-") == sym:
            try:
                return f"{int(row['cik_str']):010d}"
            except (KeyError, ValueError, TypeError):
                return None
    return None


def get_cik(symbol: str) -> str | None:
    """Resolve a ticker to its zero-padded SEC CIK, or None."""
    data = get_json(_TICKERS_URL, headers=_headers())
    return _parse_cik_map(data, symbol)


def _parse_earnings_dates(submissions_json, limit: int = 12) -> list[str]:
    """Extract 8-K Item 2.02 (earnings release) filing dates, newest first."""
    if not isinstance(submissions_json, dict):
        return []
    recent = (submissions_json.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    items = recent.get("items") or []
    out = []
    for form, fdate, fitems in zip(forms, dates, items):
        if form == "8-K" and _EARNINGS_ITEM in (fitems or ""):
            out.append(fdate)
    return out[:limit]


def get_earnings_release_dates(symbol: str, limit: int = 12) -> list[str]:
    """Official historical earnings-release dates (YYYY-MM-DD), newest first.

    Returns [] if the symbol has no CIK or the request fails.
    """
    cik = get_cik(symbol)
    if not cik:
        return []
    data = get_json(_SUBMISSIONS_URL.format(cik=cik), headers=_headers())
    return _parse_earnings_dates(data, limit)

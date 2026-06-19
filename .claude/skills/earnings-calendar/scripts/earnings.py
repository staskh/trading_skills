#!/usr/bin/env python3
# ABOUTME: CLI wrapper for earnings date retrieval.
# ABOUTME: Returns date, before/after market timing, and EPS estimate.

import argparse
import json

from trading_skills.data_sources import resolve_next_earnings_date
from trading_skills.earnings import get_earnings_info, get_multiple_earnings
from trading_skills.utils import generated_at_str


def _backfill(entry: dict) -> dict:
    """Fill a missing earnings_date via the fallback chain (NASDAQ / SEC cadence).

    Keeps the skill working when yfinance/Yahoo is rate-limited or blocked. Tags
    the provenance in `earnings_date_source` (yfinance / nasdaq / sec_estimate).
    """
    if entry.get("earnings_date"):
        entry.setdefault("earnings_date_source", "yfinance")
        return entry
    # Don't fabricate a date for a genuinely invalid ticker — keep the error.
    if "Invalid symbol" in entry.get("error", ""):
        return entry
    symbol = entry.get("symbol")
    if symbol:
        fb = resolve_next_earnings_date(symbol)
        if fb.get("date"):
            entry["earnings_date"] = fb["date"]
            entry["earnings_date_source"] = fb["source"]
            entry.pop("error", None)
    return entry


def main():
    parser = argparse.ArgumentParser(description="Get upcoming earnings dates")
    parser.add_argument("symbols", help="Ticker symbol(s), comma-separated for multiple")

    args = parser.parse_args()

    # Parse symbols
    symbols = [s.strip().upper() for s in args.symbols.split(",")]

    if len(symbols) == 1:
        result = _backfill(get_earnings_info(symbols[0]))
    else:
        result = get_multiple_earnings(symbols)
        result["results"] = [_backfill(r) for r in result.get("results", [])]
        # Re-sort: backfill may have filled dates that were previously None.
        result["results"].sort(key=lambda x: x.get("earnings_date") or "9999-99-99")

    result["generated_at"] = generated_at_str()
    # data_delay reflects provenance: an SEC cadence estimate is not a 15-min feed.
    rows = result["results"] if "results" in result else [result]
    if any(r.get("earnings_date_source") == "sec_estimate" for r in rows):
        result["data_delay"] = "estimated - projected from SEC filing cadence"
    else:
        result["data_delay"] = "15min"
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

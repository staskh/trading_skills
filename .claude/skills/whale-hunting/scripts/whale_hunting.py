#!/usr/bin/env python3
# ABOUTME: CLI script for institutional whale option activity detection.
# ABOUTME: Wraps whales_hunter() and outputs JSON with optional per-ticker summary.

import argparse
import json
import sys

import pandas as pd

from trading_skills.massive.whales import whales_hunter


def main():
    parser = argparse.ArgumentParser(description="Hunt institutional whale option activity")
    parser.add_argument("symbol", help="Underlying ticker symbol (e.g. AAPL)")
    parser.add_argument(
        "--months", type=int, default=2, help="Max months to expiration (default: 2)"
    )
    parser.add_argument(
        "--date", default=None, help="Trading date YYYY-MM-DD (default: latest trading day)"
    )
    parser.add_argument(
        "--sigma-z",
        type=float,
        default=3.5,
        dest="sigma_z",
        help="Modified Z-Score threshold for outlier detection (default: 3.5)",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Include per-ticker summary in output"
    )

    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    print(f"Hunting whales for {symbol}...", file=sys.stderr)

    result = whales_hunter(
        symbol,
        max_months=args.months,
        precise=True,
        sigma_z=args.sigma_z,
        trading_date=args.date,
    )

    whales = result["whales"]
    trading_date = result["trading_date"]

    # Aggregate call/put invested totals
    call_invested = sum(
        w["invested"] for w in whales if w.get("type") == "call" and w.get("invested")
    )
    put_invested = sum(
        w["invested"] for w in whales if w.get("type") == "put" and w.get("invested")
    )
    call_put_ratio = (call_invested / put_invested) if put_invested > 0 else None

    output = {
        "underlying": symbol,
        "trading_date": str(trading_date),
        "source": result["source"],
        "total_whales": len(whales),
        "total_call_invested": round(call_invested, 2),
        "total_put_invested": round(put_invested, 2),
        "call_put_ratio": round(call_put_ratio, 4) if call_put_ratio is not None else None,
        "whales": [
            {**w, "timestamp": str(w["timestamp"]), "expiry": str(w["expiry"])} for w in whales
        ],
    }

    if args.summary and whales:
        df = pd.DataFrame(whales)
        summary = (
            df.groupby(["ticker", "type", "strike", "expiry"])
            .agg(
                whale_count=("invested", "count"),
                total_invested=("invested", "sum"),
                break_even=("break_even", "first"),
            )
            .reset_index()
            .sort_values("total_invested", ascending=False)
        )
        summary["total_invested"] = summary["total_invested"].round(2)
        summary["expiry"] = summary["expiry"].astype(str)
        output["summary"] = summary.to_dict("records")

    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()

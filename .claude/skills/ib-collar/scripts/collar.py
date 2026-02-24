#!/usr/bin/env python3
# ABOUTME: CLI wrapper for tactical collar strategy analysis.
# ABOUTME: Returns JSON with collar scenarios and recommendations for PMCC positions.

import argparse
import asyncio
import json
import sys
from datetime import datetime

import yfinance as yf

from trading_skills.broker.collar import (
    analyze_collar,
    get_earnings_date,
    get_portfolio_positions,
)


async def main():
    parser = argparse.ArgumentParser(description="Generate tactical collar analysis")
    parser.add_argument("symbol", help="Stock symbol to analyze")
    parser.add_argument("--port", type=int, default=7496, help="IB port (default: 7496)")
    parser.add_argument("--account", type=str, default=None, help="IB account ID")

    args = parser.parse_args()
    symbol = args.symbol.upper()

    # Fetch portfolio
    print(f"Connecting to IB on port {args.port}...", file=sys.stderr)
    connected, positions, error = await get_portfolio_positions(args.port, args.account)

    if not connected:
        print(json.dumps({"error": error}))
        return

    if error:
        print(json.dumps({"error": error}))
        return

    # Filter for the symbol
    symbol_positions = [p for p in positions if p["symbol"] == symbol]

    if not symbol_positions:
        available = sorted(set(p["symbol"] for p in positions))
        print(json.dumps({"error": f"{symbol} not found in portfolio. Available: {available}"}))
        return

    # Separate long and short calls
    long_calls = [
        p for p in symbol_positions
        if p["sec_type"] == "OPT" and p["right"] == "C" and p["quantity"] > 0
    ]
    short_calls = [
        p for p in symbol_positions
        if p["sec_type"] == "OPT" and p["right"] == "C" and p["quantity"] < 0
    ]

    if not long_calls:
        print(json.dumps({"error": f"No long call positions found for {symbol}. Requires a PMCC position."}))
        return

    # Use the longest-dated long call as the LEAPS
    long_calls.sort(key=lambda x: x["expiry"], reverse=True)
    main_long = long_calls[0]

    # Get current price
    current_price = main_long.get("underlying_price")
    if not current_price:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        current_price = info.get("regularMarketPrice") or info.get("previousClose")

    if not current_price:
        print(json.dumps({"error": f"Could not get current price for {symbol}"}))
        return

    # Get earnings date
    earnings_date, _ = get_earnings_date(symbol)

    # Format short positions
    short_positions = [{
        "strike": p["strike"],
        "expiry": p["expiry"],
        "qty": abs(p["quantity"]),
    } for p in short_calls]

    # Run analysis
    print(f"Analyzing {symbol} position...", file=sys.stderr)
    analysis = analyze_collar(
        symbol=symbol,
        current_price=current_price,
        long_strike=main_long["strike"],
        long_expiry=main_long["expiry"],
        long_qty=int(main_long["quantity"]),
        long_cost=main_long["avg_cost"],
        short_positions=short_positions,
        earnings_date=earnings_date,
    )

    # Serialize datetime for JSON
    if analysis.get("earnings_date"):
        analysis["earnings_date"] = analysis["earnings_date"].strftime("%Y-%m-%d")

    print(json.dumps(analysis, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())

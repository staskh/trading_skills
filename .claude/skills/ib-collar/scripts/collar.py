#!/usr/bin/env python3
# ABOUTME: CLI wrapper for tactical collar strategy analysis.
# ABOUTME: Analyzes PMCC positions and generates collar recommendations.

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

import yfinance as yf

from trading_skills.broker.collar import (
    analyze_collar,
    generate_markdown_report,
    generate_pdf_report,
    get_earnings_date,
    get_portfolio_positions,
)


def main():
    parser = argparse.ArgumentParser(description="Generate tactical collar report")
    parser.add_argument("symbol", help="Stock symbol to analyze")
    parser.add_argument("--port", type=int, default=7496, help="IB port (default: 7496)")
    parser.add_argument("--account", type=str, default=None, help="IB account ID")

    args = parser.parse_args()
    symbol = args.symbol.upper()

    # Fetch portfolio
    print(f"Connecting to IB on port {args.port}...")
    connected, positions, error = asyncio.run(get_portfolio_positions(args.port, args.account))

    if not connected:
        print(f"Error: {error}")
        return

    if error:
        print(f"Error: {error}")
        return

    # Filter for the symbol
    symbol_positions = [p for p in positions if p["symbol"] == symbol]

    if not symbol_positions:
        print(f"Error: {symbol} not found in portfolio.")
        print("Available symbols:", sorted(set(p["symbol"] for p in positions)))
        return

    # Separate long and short calls
    long_calls = [p for p in symbol_positions if p["sec_type"] == "OPT" and p["right"] == "C" and p["quantity"] > 0]
    short_calls = [p for p in symbol_positions if p["sec_type"] == "OPT" and p["right"] == "C" and p["quantity"] < 0]

    if not long_calls:
        print(f"Error: No long call positions found for {symbol}.")
        print("Tactical collar requires a long call (PMCC) position.")
        return

    # Use the longest-dated long call as the LEAPS
    long_calls.sort(key=lambda x: x["expiry"], reverse=True)
    main_long = long_calls[0]

    # Get current price
    current_price = main_long.get("underlying_price")
    if not current_price:
        # Fallback to yfinance
        ticker = yf.Ticker(symbol)
        info = ticker.info
        current_price = info.get("regularMarketPrice") or info.get("previousClose")

    if not current_price:
        print(f"Error: Could not get current price for {symbol}")
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
    print(f"Analyzing {symbol} position...")
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

    # Generate reports
    project_root = Path(__file__).parent.parent.parent.parent.parent
    sandbox = project_root / "sandbox"
    sandbox.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Generate PDF report
    pdf_path = sandbox / f"{timestamp}_{symbol}_Tactical_Collar_Report.pdf"
    generate_pdf_report(analysis, pdf_path)

    # Generate Markdown report
    md_path = sandbox / f"{timestamp}_{symbol}_Tactical_Collar_Report.md"
    generate_markdown_report(analysis, md_path)


if __name__ == "__main__":
    main()

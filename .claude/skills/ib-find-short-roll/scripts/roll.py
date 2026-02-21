#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IB short position roll finder.
# ABOUTME: Returns JSON with roll, spread, or covered call candidates from real-time IB data.

import argparse
import asyncio
import json
import math
import sys
from datetime import datetime

from ib_async import IB

from trading_skills.broker.roll import (
    calculate_roll_options,
    evaluate_short_candidates,
    fetch_earnings_date,
    get_current_position,
    get_long_option_position,
    get_long_stock_position,
    get_option_chain_params,
    get_option_quotes,
    get_underlying_price,
)


async def main():
    parser = argparse.ArgumentParser(description="Find roll options for short position")
    parser.add_argument("symbol", type=str, help="Ticker symbol (e.g., GOOG)")
    parser.add_argument("--strike", type=float, default=None, help="Current short strike")
    parser.add_argument("--expiry", type=str, default=None, help="Current expiry (YYYYMMDD)")
    parser.add_argument("--right", type=str, default="C", choices=["C", "P"], help="Call or Put")
    parser.add_argument("--port", type=int, default=7496, help="IB port")
    parser.add_argument("--account", type=str, default=None, help="Account ID")

    args = parser.parse_args()
    symbol = args.symbol.upper()

    # Connect to IB
    ib = IB()
    try:
        print(f"Connecting to IB on port {args.port}...", file=sys.stderr)
        await ib.connectAsync("127.0.0.1", args.port, clientId=30)
    except Exception as e:
        print(json.dumps({"error": f"Could not connect to IB: {e}"}))
        return

    try:
        # Get current position or use provided parameters
        if args.strike and args.expiry:
            current_position = {
                "quantity": -1,
                "strike": args.strike,
                "expiry": args.expiry,
                "right": args.right,
                "account": args.account or "N/A",
            }
        else:
            print(f"Looking for {symbol} short positions...", file=sys.stderr)
            current_position = await get_current_position(ib, symbol, args.account)

            if not current_position:
                # No short position - check for long option first, then long stock
                print(f"No short position found. Checking for long {args.right} option...", file=sys.stderr)
                long_option = await get_long_option_position(ib, symbol, args.right, args.account)

                if long_option:
                    # Has long option - find short candidates to create a spread
                    print(f"Found long option: +{long_option['quantity']} ${long_option['strike']} {long_option['right']} exp {long_option['expiry']}", file=sys.stderr)

                    # Get underlying price
                    underlying_price = await get_underlying_price(ib, symbol)
                    if math.isnan(underlying_price):
                        underlying_price = long_option["strike"]
                        print(f"{symbol} price unavailable, using long strike ${underlying_price:.2f} as reference", file=sys.stderr)
                    else:
                        print(f"{symbol} current price: ${underlying_price:.2f}", file=sys.stderr)

                    # Get option chain parameters
                    chain_params = await get_option_chain_params(ib, symbol)

                    # Use the same expiration as the long option for a proper vertical spread
                    long_expiry = long_option["expiry"]
                    long_strike = long_option["strike"]

                    # Also check nearby expirations
                    target_exps = [e for e in chain_params["expirations"] if e >= long_expiry][:3]

                    if not target_exps:
                        print(json.dumps({"error": "No valid expirations available"}))
                        return

                    print(f"Analyzing expirations: {target_exps}", file=sys.stderr)

                    # Determine strike range (higher strikes for calls, lower for puts)
                    all_strikes = chain_params["strikes"]
                    ref_price = underlying_price

                    if args.right == "C":
                        target_strikes = [s for s in all_strikes
                                        if long_strike < s <= ref_price * 2.0]
                    else:
                        target_strikes = [s for s in all_strikes
                                        if ref_price * 0.5 <= s < long_strike]

                    target_strikes = sorted(target_strikes)[:15]
                    print(f"Target strikes: {target_strikes}", file=sys.stderr)

                    # Fetch quotes and evaluate candidates
                    candidates_by_expiry = {}
                    for exp in target_exps:
                        quotes = await get_option_quotes(ib, symbol, exp, target_strikes, args.right)
                        candidates = evaluate_short_candidates(
                            quotes, underlying_price, exp, args.right
                        )
                        if candidates:
                            candidates_by_expiry[exp] = candidates

                    # Fetch earnings date
                    earnings_date = fetch_earnings_date(symbol)

                    # Output JSON result
                    result = {
                        "success": True,
                        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "mode": "spread",
                        "symbol": symbol,
                        "underlying_price": underlying_price,
                        "right": args.right,
                        "earnings_date": earnings_date,
                        "long_option": {
                            "strike": long_option["strike"],
                            "expiry": long_option["expiry"],
                            "right": long_option["right"],
                            "quantity": long_option["quantity"],
                            "avg_cost": long_option.get("avg_cost"),
                        },
                        "candidates_by_expiry": candidates_by_expiry,
                        "expirations_analyzed": target_exps,
                    }

                    print(json.dumps(result, indent=2))
                    return

                # No long option - check for long stock to write covered calls
                print(f"No long option found. Checking for long stock...", file=sys.stderr)
                long_position = await get_long_stock_position(ib, symbol, args.account)

                if not long_position:
                    print(json.dumps({
                        "error": f"No short option or long stock position found for {symbol}. "
                                 "Use --strike and --expiry to specify a short position manually."
                    }))
                    return

                print(f"Found long stock: {long_position['quantity']} shares @ ${long_position['avg_cost']:.2f}", file=sys.stderr)

                # Get underlying price
                underlying_price = await get_underlying_price(ib, symbol)
                print(f"{symbol} current price: ${underlying_price:.2f}", file=sys.stderr)

                # Get option chain parameters
                chain_params = await get_option_chain_params(ib, symbol)

                # Determine target expirations (next 4-5 weekly/monthly)
                today_str = datetime.now().strftime("%Y%m%d")
                future_exps = [e for e in chain_params["expirations"] if e > today_str][:6]

                if not future_exps:
                    print(json.dumps({"error": "No future expirations available"}))
                    return

                print(f"Analyzing expirations: {future_exps}", file=sys.stderr)

                # Determine strike range (OTM calls for covered call strategy)
                all_strikes = chain_params["strikes"]
                if args.right == "C":
                    target_strikes = [s for s in all_strikes
                                    if underlying_price <= s <= underlying_price * 1.20]
                else:
                    target_strikes = [s for s in all_strikes
                                    if underlying_price * 0.80 <= s <= underlying_price]

                target_strikes = sorted(target_strikes)[:15]
                print(f"Target strikes: {target_strikes}", file=sys.stderr)

                # Fetch quotes and evaluate candidates
                candidates_by_expiry = {}
                for exp in future_exps:
                    quotes = await get_option_quotes(ib, symbol, exp, target_strikes, args.right)
                    candidates = evaluate_short_candidates(
                        quotes, underlying_price, exp, args.right
                    )
                    if candidates:
                        candidates_by_expiry[exp] = candidates

                # Fetch earnings date
                earnings_date = fetch_earnings_date(symbol)

                # Output JSON result
                result = {
                    "success": True,
                    "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "mode": "new_short",
                    "symbol": symbol,
                    "underlying_price": underlying_price,
                    "right": args.right,
                    "earnings_date": earnings_date,
                    "long_position": {
                        "shares": long_position["quantity"],
                        "avg_cost": long_position["avg_cost"],
                    },
                    "candidates_by_expiry": candidates_by_expiry,
                    "expirations_analyzed": future_exps,
                }

                print(json.dumps(result, indent=2))
                return

        print(f"Found position: -{abs(current_position['quantity'])} {symbol} "
              f"${current_position['strike']} {current_position['right']} "
              f"exp {current_position['expiry']}", file=sys.stderr)

        # Get underlying price
        underlying_price = await get_underlying_price(ib, symbol)
        print(f"{symbol} underlying: ${underlying_price:.2f}", file=sys.stderr)

        # Get option chain parameters
        chain_params = await get_option_chain_params(ib, symbol)

        # Get current option quote (to calculate buy-to-close cost)
        current_quotes = await get_option_quotes(
            ib, symbol,
            current_position["expiry"],
            [current_position["strike"]],
            current_position["right"]
        )

        if not current_quotes:
            print(json.dumps({"error": "Could not get quote for current position"}))
            return

        current_quote = current_quotes[0]
        buy_price = current_quote["ask"]

        # Get future expirations
        current_exp = current_position["expiry"]
        future_exps = [e for e in chain_params["expirations"] if e > current_exp][:5]

        if not future_exps:
            print(json.dumps({"error": "No future expirations available"}))
            return

        # Determine strike range
        current_strike = current_position["strike"]
        all_strikes = chain_params["strikes"]

        if current_position["right"] == "C":
            target_strikes = [s for s in all_strikes
                            if current_strike - 10 <= s <= current_strike + 50 and s % 5 == 0]
        else:
            target_strikes = [s for s in all_strikes
                            if current_strike - 50 <= s <= current_strike + 10 and s % 5 == 0]

        target_strikes = sorted(target_strikes)[:10]

        # Fetch quotes for each target expiration
        roll_data = {}
        for exp in future_exps:
            quotes = await get_option_quotes(
                ib, symbol, exp, target_strikes, current_position["right"]
            )
            roll_data[exp] = calculate_roll_options(current_position, quotes, buy_price)

        # Fetch earnings date
        print("Checking earnings date...", file=sys.stderr)
        earnings_date = fetch_earnings_date(symbol)

        # Output JSON result
        result = {
            "success": True,
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mode": "roll",
            "symbol": symbol,
            "underlying_price": underlying_price,
            "earnings_date": earnings_date,
            "current_position": {
                "strike": current_position["strike"],
                "expiry": current_position["expiry"],
                "right": current_position["right"],
                "quantity": current_position["quantity"],
            },
            "buy_to_close": buy_price,
            "roll_candidates": roll_data,
            "expirations_analyzed": future_exps,
        }

        print(json.dumps(result, indent=2))

    finally:
        ib.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

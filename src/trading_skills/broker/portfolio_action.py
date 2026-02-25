# ABOUTME: Analyzes IB portfolio positions with earnings and risk assessment.
# ABOUTME: Groups positions into spreads, categorizes by urgency/risk.

import asyncio
import sys
from collections import defaultdict
from datetime import datetime

import yfinance as yf
from ib_async import IB, Stock

from trading_skills.earnings import get_next_earnings_date
from trading_skills.technicals import compute_raw_indicators
from trading_skills.utils import days_to_expiry as _days_to_expiry


def fetch_earnings_date(symbol: str) -> dict:
    """Fetch earnings date using yfinance."""
    date_str = get_next_earnings_date(symbol)
    return {"symbol": symbol, "earnings_date": date_str}


def fetch_technicals(symbol: str, period: str = "3mo") -> dict:
    """Fetch technical indicators for a symbol."""
    result = {"symbol": symbol}

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)

        if df.empty or len(df) < 20:
            result["error"] = "Insufficient data"
            return result

        current_price = df["Close"].iloc[-1]
        raw = compute_raw_indicators(df)

        if raw["rsi"] is not None:
            result["rsi"] = round(raw["rsi"], 1)

        if raw["sma20"] is not None:
            result["sma20"] = round(raw["sma20"], 2)
            result["above_sma20"] = current_price > raw["sma20"]

        if raw["sma50"] is not None:
            result["sma50"] = round(raw["sma50"], 2)
            result["above_sma50"] = current_price > raw["sma50"]

        if raw["macd_hist"] is not None:
            result["macd_histogram"] = round(raw["macd_hist"], 3)
            result["macd_bullish"] = raw["macd_hist"] > 0

        if raw["adx"] is not None:
            result["adx"] = round(raw["adx"], 1)
            result["strong_trend"] = raw["adx"] > 25

        # Determine overall trend
        bullish_signals = 0
        bearish_signals = 0

        if result.get("rsi"):
            if result["rsi"] > 50:
                bullish_signals += 1
            else:
                bearish_signals += 1

        if result.get("above_sma20"):
            bullish_signals += 1
        elif "above_sma20" in result:
            bearish_signals += 1

        if result.get("above_sma50"):
            bullish_signals += 1
        elif "above_sma50" in result:
            bearish_signals += 1

        if result.get("macd_bullish"):
            bullish_signals += 1
        elif "macd_bullish" in result:
            bearish_signals += 1

        if bullish_signals >= 3:
            result["trend"] = "bullish"
        elif bearish_signals >= 3:
            result["trend"] = "bearish"
        else:
            result["trend"] = "neutral"

    except Exception as e:
        result["error"] = str(e)

    return result


# days_to_expiry is imported from trading_skills.utils
calculate_days_to_expiry = _days_to_expiry


def calculate_otm_pct(strike: float, underlying: float, right: str = "C") -> float:
    """Calculate OTM percentage. Positive = OTM, Negative = ITM."""
    if not underlying or not strike:
        return 0
    if right == "C":
        return ((strike - underlying) / underlying) * 100
    else:  # Put
        return ((underlying - strike) / underlying) * 100


def get_spread_recommendation(spread: dict, earnings_date: str, today: datetime) -> tuple:
    """Generate recommendation for a spread position.
    Returns (emoji, risk_level, recommendation_text)
    """
    long_pos = spread.get("long")
    short_pos = spread.get("short")
    underlying = spread.get("underlying_price", 0)

    # Parse earnings
    earnings_days = None
    if earnings_date:
        try:
            earn_dt = datetime.strptime(earnings_date, "%Y-%m-%d")
            earnings_days = (earn_dt - today).days
        except Exception:
            pass

    recommendations = []
    risk_level = "green"

    # Analyze short leg if exists
    if short_pos:
        short_days = short_pos.get("days_to_exp", 999)
        short_strike = short_pos.get("strike", 0)
        short_otm = calculate_otm_pct(short_strike, underlying) if underlying else 0
        short_itm = short_otm < 0

        if short_days <= 2:
            if short_itm:
                risk_level = "red"
                recommendations.append(
                    f"Short ${short_strike} ITM by {abs(short_otm):.0f}%, expires in {short_days}d"
                )
            else:
                recommendations.append(f"Let expire worthless (OTM by {short_otm:.0f}%)")

        elif earnings_days is not None and 0 < earnings_days < short_days:
            if short_days - earnings_days <= 3:
                risk_level = "red"
                recommendations.append(
                    f"**EARNINGS {earnings_date}!** Roll or close before earnings"
                )
            else:
                risk_level = "yellow" if risk_level != "red" else risk_level
                recommendations.append(f"Earnings {earnings_date} before expiry - monitor")

        elif short_days <= 7:
            if short_itm:
                risk_level = "red"
                recommendations.append(f"Short ITM, expires in {short_days}d - consider rolling")
            else:
                risk_level = "yellow" if risk_level != "red" else risk_level
                recommendations.append(f"Monitor - OTM by {short_otm:.0f}%")

        elif short_days <= 14:
            if short_itm:
                risk_level = "yellow" if risk_level != "red" else risk_level
                recommendations.append(f"Short ITM by {abs(short_otm):.0f}% - watch closely")

    # Analyze long leg
    if long_pos:
        long_strike = long_pos.get("strike", 0)
        long_otm = calculate_otm_pct(long_strike, underlying) if underlying else 0
        long_itm = long_otm < 0

        if long_itm:
            recommendations.append(f"Long ${long_strike} ITM by {abs(long_otm):.0f}%")
        elif long_otm > 30:
            if not short_pos:
                risk_level = "yellow" if risk_level == "green" else risk_level
                recommendations.append(f"OTM by {long_otm:.0f}% - needs rally")

    # Spread type analysis
    if long_pos and short_pos:
        long_strike = long_pos.get("strike") or 0
        short_strike = short_pos.get("strike") or 0
        long_exp = long_pos.get("expiry") or ""
        short_exp = short_pos.get("expiry") or ""

        if long_strike == 0 or short_strike == 0:
            recommendations.append("Futures position")
        elif long_exp == short_exp:
            if long_strike < short_strike:
                recommendations.append(f"Bull call spread ${long_strike}/${short_strike}")
            else:
                recommendations.append(f"Bear call spread ${short_strike}/${long_strike}")
        else:
            recommendations.append("Diagonal spread")

    if not recommendations:
        recommendations.append("OK")

    emoji = {"red": "🔴", "yellow": "🟡", "green": "🟢"}[risk_level]
    return emoji, risk_level, " | ".join(recommendations)


def group_positions_into_spreads(positions: list, symbol: str) -> list:
    """Group positions for a symbol into spreads."""
    longs = sorted(
        [p for p in positions if p["quantity"] > 0],
        key=lambda x: (x.get("expiry", ""), x.get("strike", 0)),
    )
    shorts = sorted(
        [p for p in positions if p["quantity"] < 0],
        key=lambda x: (x.get("expiry", ""), x.get("strike", 0)),
    )

    spreads = []
    used_shorts = set()

    for long_pos in longs:
        matched_short = None
        for i, short_pos in enumerate(shorts):
            if i in used_shorts:
                continue
            if abs(long_pos["quantity"]) == abs(short_pos["quantity"]):
                matched_short = short_pos
                used_shorts.add(i)
                break

        spreads.append(
            {
                "symbol": symbol,
                "long": long_pos,
                "short": matched_short,
                "quantity": abs(long_pos["quantity"]),
            }
        )

    for i, short_pos in enumerate(shorts):
        if i not in used_shorts:
            spreads.append(
                {
                    "symbol": symbol,
                    "long": None,
                    "short": short_pos,
                    "quantity": abs(short_pos["quantity"]),
                }
            )

    return spreads


async def get_portfolio_data(port: int, account: str = None) -> dict:
    """Fetch portfolio positions and prices from IB."""
    ib = IB()

    try:
        await ib.connectAsync(host="127.0.0.1", port=port, clientId=10)
    except Exception as e:
        return {"error": f"Could not connect to IB on port {port}: {e}"}

    try:
        await asyncio.sleep(2)

        if account:
            managed = ib.managedAccounts()
            if account not in managed:
                return {"error": f"Account {account} not found. Available: {managed}"}
            all_positions = ib.positions(account=account)
            accounts = [account]
        else:
            all_positions = ib.positions()
            accounts = ib.managedAccounts()

        positions_by_account = {}
        for pos in all_positions:
            acc = pos.account
            if acc not in positions_by_account:
                positions_by_account[acc] = []

            c = pos.contract
            multiplier = int(c.multiplier) if c.multiplier else 100

            positions_by_account[acc].append(
                {
                    "symbol": c.symbol,
                    "sec_type": c.secType,
                    "quantity": pos.position,
                    "avg_cost": round(pos.avgCost / multiplier, 2)
                    if c.secType == "OPT"
                    else round(pos.avgCost, 2),
                    "strike": c.strike if c.secType == "OPT" else None,
                    "expiry": c.lastTradeDateOrContractMonth if c.secType == "OPT" else None,
                    "right": c.right if c.secType == "OPT" else None,
                }
            )

        # Collect symbols, excluding futures
        symbols = set()
        futures_symbols = set()
        for positions in positions_by_account.values():
            for pos in positions:
                if pos["sec_type"] in ("FUT", "FOP"):
                    futures_symbols.add(pos["symbol"])
                else:
                    symbols.add(pos["symbol"])

        symbols = symbols - futures_symbols

        prices = {}
        if symbols:
            contracts = [Stock(sym, "SMART", "USD") for sym in symbols]
            qualified = []
            try:
                qualified = await asyncio.wait_for(ib.qualifyContractsAsync(*contracts), timeout=15)
            except asyncio.TimeoutError:
                pass

            valid_contracts = [c for c in qualified if c.conId]
            if valid_contracts:
                try:
                    tickers = await asyncio.wait_for(
                        ib.reqTickersAsync(*valid_contracts), timeout=15
                    )
                    for t in tickers:
                        p = t.marketPrice()
                        if p and p > 0:
                            prices[t.contract.symbol] = round(p, 2)
                except asyncio.TimeoutError:
                    pass

        return {
            "accounts": list(accounts),
            "positions": positions_by_account,
            "prices": prices,
        }

    finally:
        ib.disconnect()


def analyze_portfolio(data: dict) -> dict:
    """Analyze portfolio data and return structured analysis.

    Fetches earnings dates and technical indicators, groups positions
    into spreads, categorizes by urgency, and generates risk assessments.
    """
    today = datetime.now()

    positions_by_account = data.get("positions", {})
    prices = data.get("prices", {})

    # Fetch earnings dates
    all_symbols = set()
    for positions in positions_by_account.values():
        for pos in positions:
            all_symbols.add(pos["symbol"])

    print("Fetching earnings dates...", file=sys.stderr)
    earnings = {}
    for sym in all_symbols:
        result = fetch_earnings_date(sym)
        earnings[sym] = result.get("earnings_date")

    print("Fetching technical indicators...", file=sys.stderr)
    technicals = {}
    for sym in all_symbols:
        technicals[sym] = fetch_technicals(sym)

    # Add days_to_exp and underlying_price to all positions
    for acc, positions in positions_by_account.items():
        for pos in positions:
            if pos["expiry"]:
                pos["days_to_exp"] = calculate_days_to_expiry(pos["expiry"])
            else:
                pos["days_to_exp"] = 999
            pos["underlying_price"] = prices.get(pos["symbol"])
            pos["earnings_date"] = earnings.get(pos["symbol"])

    # Group positions by symbol and account, then into spreads
    spreads_by_account = {}
    for acc, positions in positions_by_account.items():
        by_symbol = defaultdict(list)
        for pos in positions:
            by_symbol[pos["symbol"]].append(pos)

        spreads_by_account[acc] = {}
        for symbol, pos_list in by_symbol.items():
            spreads_by_account[acc][symbol] = group_positions_into_spreads(pos_list, symbol)
            for spread in spreads_by_account[acc][symbol]:
                spread["underlying_price"] = prices.get(symbol)
                spread["earnings_date"] = earnings.get(symbol)

    # Categorize spreads by urgency
    expiring_2_days = []
    expiring_1_week = []
    expiring_2_weeks = []
    earnings_this_week = []
    earnings_next_week = []
    longer_dated = []

    red_count = 0
    yellow_count = 0
    green_count = 0

    all_spreads = []

    for acc, symbols in spreads_by_account.items():
        for symbol, spreads in symbols.items():
            for spread in spreads:
                spread["account"] = acc
                earnings_date = spread.get("earnings_date")
                emoji, level, rec = get_spread_recommendation(spread, earnings_date, today)
                spread["risk_emoji"] = emoji
                spread["risk_level"] = level
                spread["recommendation"] = rec

                if level == "red":
                    red_count += 1
                elif level == "yellow":
                    yellow_count += 1
                else:
                    green_count += 1

                min_days = 999
                if spread.get("short"):
                    min_days = min(min_days, spread["short"].get("days_to_exp", 999))
                if spread.get("long"):
                    min_days = min(min_days, spread["long"].get("days_to_exp", 999))

                spread["min_days_to_exp"] = min_days

                earnings_days = None
                if earnings_date:
                    try:
                        earn_dt = datetime.strptime(earnings_date, "%Y-%m-%d")
                        earnings_days = (earn_dt - today).days
                    except Exception:
                        pass

                spread["urgency"] = (
                    "expiring_2_days"
                    if min_days <= 2
                    else "expiring_1_week"
                    if min_days <= 9
                    else "expiring_2_weeks"
                    if min_days <= 21
                    else "longer_dated"
                )

                if min_days <= 2:
                    expiring_2_days.append(spread)
                elif min_days <= 9:
                    expiring_1_week.append(spread)
                elif min_days <= 21:
                    expiring_2_weeks.append(spread)
                else:
                    longer_dated.append(spread)

                if earnings_days is not None:
                    if 0 <= earnings_days <= 3:
                        spread["earnings_urgency"] = "this_week"
                        earnings_this_week.append(spread)
                    elif 4 <= earnings_days <= 10:
                        spread["earnings_urgency"] = "next_week"
                        earnings_next_week.append(spread)

                all_spreads.append(spread)

    # Detect major earnings today
    today_earnings = [
        s for s in all_spreads if s.get("earnings_date") == today.strftime("%Y-%m-%d")
    ]
    today_symbols = list(set(s["symbol"] for s in today_earnings))

    # Build earnings calendar
    upcoming_earnings = [(sym, dt) for sym, dt in earnings.items() if dt]
    upcoming_earnings.sort(key=lambda x: x[1])
    upcoming_earnings = [(s, d) for s, d in upcoming_earnings if d >= today.strftime("%Y-%m-%d")]

    earnings_calendar = []
    for sym, dt in upcoming_earnings[:20]:
        accs = []
        pos_types = []
        for acc, symbols in spreads_by_account.items():
            if sym in symbols:
                accs.append(acc)
                acc_spreads = symbols[sym]
                if any(s.get("long") and s.get("short") for s in acc_spreads):
                    pos_types.append("Spread")
                elif any(s.get("long") for s in acc_spreads):
                    pos_types.append("Long")
                else:
                    pos_types.append("Short")
        if accs:
            earnings_calendar.append(
                {
                    "date": dt,
                    "symbol": sym,
                    "accounts": accs,
                    "position_types": list(set(pos_types)),
                }
            )

    # Account summary
    account_summary = []
    for acc in data.get("accounts", []):
        acc_positions = positions_by_account.get(acc, [])
        acc_spreads = [s for s in all_spreads if s["account"] == acc]
        account_summary.append(
            {
                "account": acc,
                "position_count": len(acc_positions),
                "spread_count": len(acc_spreads),
                "red_count": sum(1 for s in acc_spreads if s["risk_level"] == "red"),
                "yellow_count": sum(1 for s in acc_spreads if s["risk_level"] == "yellow"),
                "green_count": sum(1 for s in acc_spreads if s["risk_level"] == "green"),
            }
        )

    return {
        "generated": today.strftime("%Y-%m-%d %H:%M"),
        "accounts": data.get("accounts", []),
        "summary": {
            "red_count": red_count,
            "yellow_count": yellow_count,
            "green_count": green_count,
        },
        "today_earnings_symbols": today_symbols,
        "spreads": all_spreads,
        "earnings": earnings,
        "technicals": technicals,
        "prices": prices,
        "earnings_calendar": earnings_calendar,
        "account_summary": account_summary,
    }

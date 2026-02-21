# ABOUTME: Generates IB portfolio action report with earnings and risk.
# ABOUTME: Groups positions into spreads, categorizes by urgency/risk.

import asyncio
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
from ib_async import IB, Stock

from trading_skills.earnings import get_next_earnings_date
from trading_skills.technicals import compute_raw_indicators
from trading_skills.utils import days_to_expiry as _days_to_expiry
from trading_skills.utils import format_expiry_short


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


# days_to_expiry and format_expiry_short are imported from trading_skills.utils
calculate_days_to_expiry = _days_to_expiry
format_expiry = format_expiry_short


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


def _spread_row(s: dict, pos: dict, qty: str, underlying) -> str:
    """Build the common columns of a spread table row."""
    right = pos.get("right", "C")
    strike = pos.get("strike", "-")
    exp = format_expiry(pos.get("expiry"))
    cost = pos.get("avg_cost", "-")
    return (
        f"| **{s['symbol']}** | {qty} {right}"
        f" | ${strike} | {exp} | ${cost} | ${underlying} |"
    )


def _earn_pos_row(pos: dict, sign: str, status: str) -> str:
    """Build an earnings position table row."""
    qty = abs(pos["quantity"])
    right = pos.get("right", "C")
    strike = pos.get("strike", "-")
    exp = format_expiry(pos.get("expiry"))
    cost = pos.get("avg_cost", "-")
    return (
        f"| {sign}{qty:.0f} {right} | ${strike}"
        f" | {exp} | ${cost} | {status} |"
    )


def generate_report(data: dict, output_path: Path) -> str:
    """Generate the markdown report."""
    analysis = analyze_portfolio(data)

    today = datetime.now()
    date_str = today.strftime("%B %d, %Y at %H:%M")

    all_spreads = analysis["spreads"]
    prices = analysis["prices"]
    technicals = analysis["technicals"]
    today_symbols = analysis["today_earnings_symbols"]
    red_count = analysis["summary"]["red_count"]
    yellow_count = analysis["summary"]["yellow_count"]
    green_count = analysis["summary"]["green_count"]

    expiring_2_days = [s for s in all_spreads if s.get("urgency") == "expiring_2_days"]
    expiring_1_week = [s for s in all_spreads if s.get("urgency") == "expiring_1_week"]
    expiring_2_weeks = [s for s in all_spreads if s.get("urgency") == "expiring_2_weeks"]
    longer_dated = [s for s in all_spreads if s.get("urgency") == "longer_dated"]
    earnings_this_week = [s for s in all_spreads if s.get("earnings_urgency") == "this_week"]
    earnings_next_week = [s for s in all_spreads if s.get("earnings_urgency") == "next_week"]

    # Build report
    lines = [
        "# IB Portfolio Action Report - All Accounts",
        f"**Generated:** {date_str}",
    ]

    if today_symbols:
        lines.append(
            f"**Market Status:** Earnings day ({', '.join(today_symbols)} reporting today)"
        )
    lines.extend(["", "---", ""])

    # Critical Summary
    lines.extend(
        [
            "## CRITICAL SUMMARY",
            "",
            "| Status | Count | Description |",
            "|--------|-------|-------------|",
            f"| 🔴 **RED** | {red_count} | Immediate action required |",
            f"| 🟡 **YELLOW** | {yellow_count} | Warning - earnings/expiration within 2 weeks |",
            f"| 🟢 **GREEN** | {green_count} | Monitor - no immediate action needed |",
            "",
            "---",
            "",
        ]
    )

    # Helper to render spread sections by account
    def render_section(title, spread_list, show_earnings=False):
        if not spread_list:
            return
        lines.extend([title, ""])

        by_account = defaultdict(list)
        for s in spread_list:
            by_account[s["account"]].append(s)

        for acc, spreads in by_account.items():
            if show_earnings:
                hdr = (
                    "| Symbol | Position | Strike | Exp "
                    "| Avg Cost | Underlying | Earnings | Action |"
                )
                sep = (
                    "|--------|----------|--------|-----"
                    "|----------|------------|----------|--------|"
                )
                lines.extend(
                    [f"### Account {acc}", "", hdr, sep]
                )
            else:
                lines.extend(
                    [
                        f"### Account {acc}",
                        "",
                        "| Symbol | Position | Strike | Exp | Avg Cost | Underlying | Action |",
                        "|--------|----------|--------|-----|----------|------------|--------|",
                    ]
                )

            for s in spreads:
                earn = s.get("earnings_date") or "-"
                ulying = s.get("underlying_price", "-")
                action = (
                    f"{s['risk_emoji']} {s['recommendation']}"
                )

                if s.get("short"):
                    pos = s["short"]
                    qty = f"-{abs(pos['quantity']):.0f}"
                    row = _spread_row(s, pos, qty, ulying)
                    if show_earnings:
                        lines.append(f"{row} {earn} | {action} |")
                    else:
                        lines.append(f"{row} {action} |")
                if s.get("long") and not s.get("short"):
                    pos = s["long"]
                    qty = f"+{abs(pos['quantity']):.0f}"
                    row = _spread_row(s, pos, qty, ulying)
                    if show_earnings:
                        lines.append(f"{row} {earn} | {action} |")
                    else:
                        lines.append(f"{row} {action} |")
            lines.append("")
        lines.extend(["---", ""])

    if expiring_2_days:
        exp_date = (today + timedelta(days=2)).strftime("%b %d, %Y")
        render_section(
            f"## 🔴 IMMEDIATE ACTION REQUIRED (Expiring ~{exp_date} - 2 DAYS)", expiring_2_days
        )

    if expiring_1_week:
        render_section("## 🔴 URGENT - Expiring Within 1 Week", expiring_1_week, show_earnings=True)

    # Earnings sections
    def render_earnings_section(title, spread_list):
        if not spread_list:
            return
        lines.extend([title, ""])

        by_symbol = defaultdict(list)
        for s in spread_list:
            by_symbol[s["symbol"]].append(s)

        for symbol, spreads in by_symbol.items():
            earn_date = spreads[0].get("earnings_date", "")
            underlying = spreads[0].get("underlying_price", 0)

            for s in spreads:
                acc = s["account"]
                lines.extend(
                    [
                        f"### {symbol} Reports {earn_date}",
                        "",
                        f"**Account {acc}:**",
                        f"| Position | Strike | Exp | Avg Cost | Underlying: ${underlying} |",
                        "|----------|--------|-----|----------|" + "-" * 20 + "|",
                    ]
                )

                if s.get("long"):
                    pos = s["long"]
                    otm = calculate_otm_pct(pos.get("strike", 0), underlying)
                    status = f"ITM by {abs(otm):.0f}%" if otm < 0 else f"OTM by {otm:.0f}%"
                    lines.append(_earn_pos_row(pos, "+", status))

                if s.get("short"):
                    pos = s["short"]
                    otm = calculate_otm_pct(pos.get("strike", 0), underlying)
                    status = f"ITM by {abs(otm):.0f}%" if otm < 0 else f"OTM by {otm:.0f}%"
                    lines.append(_earn_pos_row(pos, "-", status))

                lines.extend(
                    [
                        "",
                        f"{s['risk_emoji']} **ACTION:** {s['recommendation']}",
                        "",
                    ]
                )
        lines.extend(["---", ""])

    render_earnings_section("## 🔴 CRITICAL EARNINGS ALERT - This Week", earnings_this_week)
    render_earnings_section("## 🟡 EARNINGS NEXT WEEK", earnings_next_week)

    if expiring_2_weeks:
        render_section("## 🟡 EXPIRING IN 2 WEEKS", expiring_2_weeks, show_earnings=True)

    # Longer dated positions
    if longer_dated:
        lines.extend(
            [
                "## 🟢 LONGER-DATED POSITIONS (No Immediate Action)",
                "",
            ]
        )

        by_account = defaultdict(list)
        for s in longer_dated:
            by_account[s["account"]].append(s)

        for acc, spreads in by_account.items():
            lines.extend(
                [
                    f"### Account {acc} - Core Holdings",
                    "",
                    "| Spread | Long | Short | Underlying | Status |",
                    "|--------|------|-------|------------|--------|",
                ]
            )
            for s in spreads:
                symbol = s["symbol"]
                underlying = s.get("underlying_price", "-")

                long_str = "-"
                short_str = "-"

                if s.get("long"):
                    pos = s["long"]
                    qty = abs(pos["quantity"])
                    strike = pos.get("strike")
                    exp = format_expiry(pos.get("expiry"))
                    long_str = f"+{qty:.0f} ${strike} {exp}"

                if s.get("short"):
                    pos = s["short"]
                    qty = abs(pos["quantity"])
                    strike = pos.get("strike")
                    exp = format_expiry(pos.get("expiry"))
                    short_str = f"-{qty:.0f} ${strike} {exp}"

                action = (
                    f"{s['risk_emoji']} {s['recommendation']}"
                )
                lines.append(
                    f"| {symbol} | {long_str} | {short_str}"
                    f" | ${underlying} | {action} |"
                )
            lines.append("")
        lines.extend(["---", ""])

    # Top Priority Actions
    red_spreads = [s for s in all_spreads if s["risk_level"] == "red"]
    yellow_spreads = [s for s in all_spreads if s["risk_level"] == "yellow"]

    if red_spreads or yellow_spreads:
        lines.extend(["## TOP PRIORITY ACTIONS", ""])

        if red_spreads:
            lines.extend([f"### 🔴 DO TODAY ({today.strftime('%b %d')})", ""])
            for i, s in enumerate(red_spreads[:5], 1):
                symbol = s["symbol"]
                acc = s["account"]
                short_pos = s.get("short", {})
                strike = short_pos.get("strike", "-") if short_pos else "-"
                exp = format_expiry(short_pos.get("expiry")) if short_pos else "-"
                lines.extend(
                    [
                        f"{i}. **{symbol} ${strike} {exp}** ({acc})",
                        f"   - {s['recommendation']}",
                        "",
                    ]
                )

        if yellow_spreads:
            lines.extend(["### 🟡 MONITOR THIS WEEK", ""])
            for i, s in enumerate(yellow_spreads[:5], 1):
                symbol = s["symbol"]
                acc = s["account"]
                lines.extend(
                    [
                        f"{i}. **{symbol}** ({acc})",
                        f"   - {s['recommendation']}",
                        "",
                    ]
                )

        lines.extend(["---", ""])

    # Position Size Summary
    lines.extend(
        [
            "## POSITION SIZE SUMMARY BY ACCOUNT",
            "",
            "| Account | Positions | Spreads | 🔴 Red | 🟡 Yellow | 🟢 Green |",
            "|---------|-----------|---------|--------|----------|---------|",
        ]
    )

    total_positions = 0
    total_spreads = 0

    for entry in analysis["account_summary"]:
        total_positions += entry["position_count"]
        total_spreads += entry["spread_count"]

        e = entry
        lines.append(
            f"| {e['account']} | {e['position_count']}"
            f" | {e['spread_count']} | {e['red_count']}"
            f" | {e['yellow_count']} | {e['green_count']} |"
        )

    lines.append(
        f"| **TOTAL** | **{total_positions}**"
        f" | **{total_spreads}** | **{red_count}**"
        f" | **{yellow_count}** | **{green_count}** |"
    )
    lines.extend(["", "---", ""])

    # Earnings Calendar
    earnings_calendar = analysis["earnings_calendar"]

    if earnings_calendar:
        lines.extend(
            [
                "## EARNINGS CALENDAR (Next 30 Days)",
                "",
                "| Date | Symbol | Account | Position Type |",
                "|------|--------|---------|---------------|",
            ]
        )

        for entry in earnings_calendar:
            accts = ", ".join(entry["accounts"])
            ptypes = ", ".join(entry["position_types"])
            lines.append(
                f"| **{entry['date']}** | {entry['symbol']}"
                f" | {accts} | {ptypes} |"
            )

        lines.extend(["", "---", ""])

    # Technical Analysis Section
    if technicals:
        lines.extend(
            [
                "## TECHNICAL ANALYSIS SUMMARY",
                "",
                "| Symbol | Price | RSI | Trend | SMA20 | SMA50 | MACD | ADX |",
                "|--------|-------|-----|-------|-------|-------|------|-----|",
            ]
        )

        for sym in sorted(technicals.keys()):
            tech = technicals[sym]
            price = prices.get(sym, "-")

            if "error" in tech:
                lines.append(f"| {sym} | ${price} | - | - | - | - | - | - |")
                continue

            rsi = tech.get("rsi", "-")
            if isinstance(rsi, float):
                if rsi > 70:
                    rsi_str = f"**{rsi}** 🔴"
                elif rsi < 30:
                    rsi_str = f"**{rsi}** 🟢"
                else:
                    rsi_str = str(rsi)
            else:
                rsi_str = "-"

            trend = tech.get("trend", "-")
            trend_emoji = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(trend, "")
            trend_str = f"{trend} {trend_emoji}"

            sma20 = tech.get("sma20", "-")
            above20 = "✓" if tech.get("above_sma20") else "✗" if "above_sma20" in tech else ""
            sma20_str = f"${sma20} {above20}" if isinstance(sma20, float) else "-"

            sma50 = tech.get("sma50", "-")
            above50 = "✓" if tech.get("above_sma50") else "✗" if "above_sma50" in tech else ""
            sma50_str = f"${sma50} {above50}" if isinstance(sma50, float) else "-"

            macd_hist = tech.get("macd_histogram", "-")
            if isinstance(macd_hist, float):
                macd_str = f"{macd_hist:+.3f}" if macd_hist != 0 else "0.000"
            else:
                macd_str = "-"

            adx = tech.get("adx", "-")
            if isinstance(adx, float):
                adx_str = f"**{adx}**" if adx > 25 else str(adx)
            else:
                adx_str = "-"

            lines.append(
                f"| **{sym}** | ${price} | {rsi_str}"
                f" | {trend_str} | {sma20_str} | {sma50_str}"
                f" | {macd_str} | {adx_str} |"
            )

        lines.extend(
            [
                "",
                "**Legend:** RSI >70 = overbought 🔴, RSI <30 = oversold 🟢"
                " | ✓ = price above MA | ADX >25 = strong trend",
                "",
                "---",
                "",
            ]
        )

    # Sources
    lines.extend(
        [
            "## Sources",
            "",
            "- [MarketBeat Earnings Calendar](https://www.marketbeat.com/earnings/)",
            "- [Nasdaq Earnings](https://www.nasdaq.com/market-activity/earnings)",
            "- [Yahoo Finance Earnings Calendar](https://finance.yahoo.com/calendar/earnings)",
            "",
            "---",
            "",
            f"*Report generated by Trading Skills on {today.strftime('%Y-%m-%d %H:%M')}*",
        ]
    )

    report_content = "\n".join(lines)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_content, encoding="utf-8")

    return report_content


def convert_to_pdf(markdown_path: Path, pdf_path: Path) -> bool:
    """Convert markdown to PDF using fpdf2."""
    try:
        from fpdf import FPDF

        md_content = markdown_path.read_text(encoding="utf-8")

        pdf = FPDF(orientation="L", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        emoji_map = {
            "🔴": "[!]",
            "🟡": "[?]",
            "🟢": "[OK]",
            "📈": "[UP]",
            "📉": "[DN]",
            "➡️": "[--]",
            "✓": "[Y]",
            "✗": "[N]",
        }
        for emoji, text in emoji_map.items():
            md_content = md_content.replace(emoji, text)

        in_table = False
        table_data = []

        for line in md_content.split("\n"):
            line = line.strip()

            if not line:
                if in_table and table_data:
                    render_table(pdf, table_data)
                    table_data = []
                    in_table = False
                pdf.ln(2)
                continue

            if line.startswith("# "):
                pdf.set_font("Helvetica", "B", 14)
                pdf.cell(0, 8, line[2:])
                pdf.ln(10)
            elif line.startswith("## "):
                pdf.set_font("Helvetica", "B", 11)
                pdf.cell(0, 6, line[3:])
                pdf.ln(8)
            elif line.startswith("### "):
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(0, 5, line[4:])
                pdf.ln(7)
            elif line.startswith("---"):
                pdf.ln(1)
                pdf.set_draw_color(200, 200, 200)
                pdf.line(10, pdf.get_y(), 280, pdf.get_y())
                pdf.ln(3)
            elif line.startswith("|"):
                in_table = True
                if not line.startswith("|--") and not line.startswith("|-"):
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    if cells:
                        table_data.append(cells)
            elif line.startswith("**"):
                pdf.set_font("Helvetica", "B", 9)
                text = line.replace("**", "")
                pdf.cell(0, 4, text[:120])
                pdf.ln(5)
            elif line.startswith("- "):
                pdf.set_font("Helvetica", "", 8)
                pdf.cell(5, 4, "-")
                pdf.cell(0, 4, line[2:][:100])
                pdf.ln(5)
            elif re.match(r"^\d+\.", line):
                pdf.set_font("Helvetica", "", 8)
                pdf.cell(0, 4, line[:100])
                pdf.ln(5)
            else:
                pdf.set_font("Helvetica", "", 8)
                text = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
                text = re.sub(r"\*(.+?)\*", r"\1", text)
                text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
                if text:
                    pdf.cell(0, 4, text[:150])
                    pdf.ln(5)

        if in_table and table_data:
            render_table(pdf, table_data)

        pdf.output(str(pdf_path))
        return True

    except ImportError:
        print("fpdf2 not installed. Run: uv add fpdf2", file=sys.stderr)
        return False
    except Exception as e:
        print(f"PDF generation error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return False


def render_table(pdf, table_data: list):
    """Render a table in the PDF."""
    if not table_data:
        return

    num_cols = len(table_data[0]) if table_data else 0
    if num_cols == 0:
        return

    if num_cols > 12:
        pdf.set_font("Helvetica", "I", 7)
        pdf.cell(0, 4, f"[Table with {num_cols} columns - see markdown for details]")
        pdf.ln(5)
        return

    page_width = 270
    col_width = page_width / num_cols
    font_size = 6 if num_cols > 6 else 7

    pdf.set_font("Helvetica", "B", font_size)
    pdf.set_fill_color(240, 240, 240)
    for cell in table_data[0]:
        max_chars = max(8, int(col_width / 1.8))
        cell_text = (cell[:max_chars] + "..") if len(cell) > max_chars else cell
        pdf.cell(col_width, 4, cell_text, border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", font_size)
    for row in table_data[1:]:
        for i in range(num_cols):
            cell = row[i] if i < len(row) else ""
            max_chars = max(8, int(col_width / 1.8))
            cell_text = (cell[:max_chars] + "..") if len(cell) > max_chars else cell
            pdf.cell(col_width, 4, cell_text, border=1)
        pdf.ln()

# ABOUTME: Generates tactical collar strategy reports for PMCC positions.
# ABOUTME: Analyzes earnings risk and recommends optimal put protection.

import asyncio
import math
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
from ib_async import IB, Stock

from trading_skills.black_scholes import black_scholes_price
from trading_skills.earnings import get_next_earnings_date
from trading_skills.options import get_expiries
from trading_skills.utils import annualized_volatility


def format_pnl(value: float) -> str:
    """Format a P&L value as 'gains $X' or 'loses $X'."""
    if value >= 0:
        return f"gains ${value:,.0f}"
    else:
        return f"loses ${abs(value):,.0f}"


def get_earnings_date(symbol: str) -> tuple[datetime | None, str]:
    """Get next earnings date for a symbol as (datetime, timing_str)."""
    try:
        date_str = get_next_earnings_date(symbol)
        if date_str:
            return datetime.strptime(date_str, "%Y-%m-%d"), "after market close"
    except Exception:
        pass
    return None, ""


def get_stock_volatility(symbol: str, period: str = "3mo") -> dict:
    """Calculate stock's historical volatility and expected move."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        if hist.empty or len(hist) < 20:
            return {"error": "Insufficient data"}

        # Calculate volatility
        returns, daily_vol, annual_vol = annualized_volatility(hist["Close"])

        # Calculate expected moves for different time periods
        # Using 1 standard deviation move
        current_price = hist["Close"].iloc[-1]

        # Expected move over N days = price * daily_vol * sqrt(N)
        move_1_week = current_price * daily_vol * math.sqrt(5)
        move_2_weeks = current_price * daily_vol * math.sqrt(10)
        move_3_weeks = current_price * daily_vol * math.sqrt(15)

        # Volatility classification
        if annual_vol > 0.80:
            vol_class = "EXTREME"
        elif annual_vol > 0.60:
            vol_class = "VERY HIGH"
        elif annual_vol > 0.40:
            vol_class = "HIGH"
        elif annual_vol > 0.25:
            vol_class = "MODERATE"
        else:
            vol_class = "LOW"

        return {
            "current_price": current_price,
            "daily_vol": daily_vol,
            "annual_vol": annual_vol,
            "annual_vol_pct": annual_vol * 100,
            "move_1_week": move_1_week,
            "move_1_week_pct": (move_1_week / current_price) * 100,
            "move_2_weeks": move_2_weeks,
            "move_2_weeks_pct": (move_2_weeks / current_price) * 100,
            "move_3_weeks": move_3_weeks,
            "move_3_weeks_pct": (move_3_weeks / current_price) * 100,
            "vol_class": vol_class,
        }
    except Exception as e:
        return {"error": str(e)}


def get_put_chain(symbol: str, target_expiry: str) -> list[dict]:
    """Get put options for a specific expiry."""
    try:
        ticker = yf.Ticker(symbol)
        if target_expiry not in ticker.options:
            return []
        chain = ticker.option_chain(target_expiry)
        puts = chain.puts
        result = []
        for _, row in puts.iterrows():
            result.append(
                {
                    "strike": row["strike"],
                    "bid": row["bid"],
                    "ask": row["ask"],
                    "mid": (row["bid"] + row["ask"]) / 2,
                    "oi": row["openInterest"],
                    "iv": row.get("impliedVolatility", 0.4),
                }
            )
        return result
    except Exception:
        return []


get_available_expiries = get_expiries


def get_call_market_price(symbol: str, strike: float, expiry: str) -> float | None:
    """Get actual market price for a call option.

    Args:
        symbol: Stock symbol
        strike: Option strike price
        expiry: Expiry date in YYYYMMDD format (from IB) or YYYY-MM-DD format

    Returns:
        Mid price of the option, or None if not found
    """
    try:
        ticker = yf.Ticker(symbol)

        # Convert YYYYMMDD to YYYY-MM-DD if needed
        if len(expiry) == 8 and "-" not in expiry:
            expiry_formatted = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
        else:
            expiry_formatted = expiry

        # Get available expiries and find closest match
        available = ticker.options
        if expiry_formatted not in available:
            # Try to find the closest expiry
            target_date = datetime.strptime(expiry_formatted, "%Y-%m-%d")
            closest = None
            min_diff = float("inf")
            for exp in available:
                exp_date = datetime.strptime(exp, "%Y-%m-%d")
                diff = abs((exp_date - target_date).days)
                if diff < min_diff:
                    min_diff = diff
                    closest = exp
            if closest and min_diff <= 7:  # Within a week
                expiry_formatted = closest
            else:
                return None

        chain = ticker.option_chain(expiry_formatted)
        calls = chain.calls

        # Find the strike
        matching = calls[calls["strike"] == strike]
        if matching.empty:
            # Try to find closest strike
            if calls.empty:
                return None
            closest_idx = (calls["strike"] - strike).abs().idxmin()
            matching = calls.loc[[closest_idx]]
            if abs(matching.iloc[0]["strike"] - strike) > 5:  # More than $5 off
                return None

        row = matching.iloc[0]
        bid = row["bid"]
        ask = row["ask"]

        # Use mid price, or last price if bid/ask is zero
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        elif row.get("lastPrice", 0) > 0:
            return row["lastPrice"]

        return None
    except Exception as e:
        print(f"Warning: Could not fetch call price for {symbol} {strike} {expiry}: {e}")
        return None


def analyze_collar(
    symbol: str,
    current_price: float,
    long_strike: float,
    long_expiry: str,
    long_qty: int,
    long_cost: float,
    short_positions: list[dict],
    earnings_date: datetime | None,
) -> dict:
    """Analyze tactical collar strategy for the position."""
    today = datetime.now()

    # Get stock volatility for timing recommendations
    volatility = get_stock_volatility(symbol)

    # PMCC health check
    is_proper_pmcc = current_price >= long_strike * 0.95  # Within 5% of strike
    short_above_long = all(s["strike"] >= long_strike for s in short_positions)

    # Days to earnings
    days_to_earnings = (earnings_date - today).days if earnings_date else None

    # Get available expiries
    expiries = get_available_expiries(symbol)

    # Find suitable put expiries (after earnings if applicable)
    put_expiries = []
    if earnings_date and expiries:
        for exp in expiries:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_after_earnings = (exp_date - earnings_date).days
            days_from_now = (exp_date - today).days
            if 0 < days_after_earnings <= 60 and days_from_now > 0:
                put_expiries.append(
                    {
                        "expiry": exp,
                        "days_out": days_from_now,
                        "days_after_earnings": days_after_earnings,
                    }
                )
    elif expiries:
        # No earnings, just get near-term expiries
        for exp in expiries[:6]:
            exp_date = datetime.strptime(exp, "%Y-%m-%d")
            days_from_now = (exp_date - today).days
            if days_from_now > 7:
                put_expiries.append(
                    {
                        "expiry": exp,
                        "days_out": days_from_now,
                        "days_after_earnings": None,
                    }
                )

    # Determine put strikes at various OTM levels (deduplicated)
    put_strike_5 = round(current_price * 0.95 / 5) * 5  # 5% OTM, round to 5
    put_strike_10 = round(current_price * 0.90 / 5) * 5  # 10% OTM
    put_strike_15 = round(current_price * 0.85 / 5) * 5  # 15% OTM
    # Deduplicate strikes (can happen when rounding)
    put_strikes = list(dict.fromkeys([put_strike_15, put_strike_10, put_strike_5]))

    # IV estimates
    iv_before = 0.50  # Elevated before earnings
    iv_after_up = 0.35  # Crushed after gap up
    iv_after_down = 0.45  # Stays elevated after gap down

    # Analyze each put expiry
    put_analysis = []
    for pe in put_expiries[:4]:  # Analyze up to 4 expiries
        T_before = pe["days_out"] / 365
        days_after = pe.get("days_after_earnings") or 7
        T_after = days_after / 365

        for put_strike in put_strikes:
            otm_pct = (current_price - put_strike) / current_price * 100

            # Get actual put price if available
            puts = get_put_chain(symbol, pe["expiry"])
            actual_put = next((p for p in puts if p["strike"] == put_strike), None)

            if actual_put:
                put_cost = actual_put["mid"]
            else:
                put_cost = black_scholes_price(
                    current_price, put_strike, T_before, 0.05, iv_before, "put"
                )

            total_cost = put_cost * long_qty * 100

            # Scenario analysis
            scenarios = {}

            # Gap up 10%
            price_up = current_price * 1.10
            put_value_up = black_scholes_price(
                price_up, put_strike, T_after, 0.05, iv_after_up, "put"
            )
            scenarios["gap_up_10"] = {
                "price": price_up,
                "put_value": put_value_up * long_qty * 100,
                "put_pnl": (put_value_up - put_cost) * long_qty * 100,
            }

            # Flat
            put_value_flat = black_scholes_price(
                current_price, put_strike, T_after, 0.05, 0.40, "put"
            )
            scenarios["flat"] = {
                "price": current_price,
                "put_value": put_value_flat * long_qty * 100,
                "put_pnl": (put_value_flat - put_cost) * long_qty * 100,
            }

            # Gap down 10%
            price_down = current_price * 0.90
            put_value_down = black_scholes_price(
                price_down, put_strike, T_after, 0.05, iv_after_down, "put"
            )
            put_value_down = max(put_value_down, put_strike - price_down)  # At least intrinsic
            scenarios["gap_down_10"] = {
                "price": price_down,
                "put_value": put_value_down * long_qty * 100,
                "put_pnl": (put_value_down - put_cost) * long_qty * 100,
            }

            # Gap down 15%
            price_down_15 = current_price * 0.85
            put_value_down_15 = black_scholes_price(
                price_down_15, put_strike, T_after, 0.05, iv_after_down, "put"
            )
            put_value_down_15 = max(put_value_down_15, put_strike - price_down_15)
            scenarios["gap_down_15"] = {
                "price": price_down_15,
                "put_value": put_value_down_15 * long_qty * 100,
                "put_pnl": (put_value_down_15 - put_cost) * long_qty * 100,
            }

            put_analysis.append(
                {
                    "expiry": pe["expiry"],
                    "days_out": pe["days_out"],
                    "days_after_earnings": pe.get("days_after_earnings"),
                    "strike": put_strike,
                    "otm_pct": otm_pct,
                    "cost_per_contract": put_cost,
                    "total_cost": total_cost,
                    "scenarios": scenarios,
                }
            )

    # Calculate long call risk without protection
    T_long = (datetime.strptime(long_expiry, "%Y%m%d") - today).days / 365

    # Try to get actual market price for the long call
    actual_long_price = get_call_market_price(symbol, long_strike, long_expiry)

    if actual_long_price:
        long_value_now = actual_long_price
        if current_price >= long_strike * 0.95:  # Near/ITM
            long_value_down_10 = max(0.1, long_value_now - (current_price * 0.10 * 0.55))
            long_value_down_15 = max(0.1, long_value_now - (current_price * 0.15 * 0.50))
            long_value_up_10 = long_value_now + (current_price * 0.10 * 0.60)
        else:  # OTM
            otm_ratio = current_price / long_strike
            long_value_down_10 = max(0.1, long_value_now * (0.70 * otm_ratio))
            long_value_down_15 = max(0.1, long_value_now * (0.55 * otm_ratio))
            long_value_up_10 = long_value_now + (current_price * 0.10 * 0.45)
    else:
        long_value_now = black_scholes_price(current_price, long_strike, T_long, 0.05, 0.60, "call")
        long_value_down_10 = black_scholes_price(
            current_price * 0.90, long_strike, T_long, 0.05, 0.65, "call"
        )
        long_value_down_15 = black_scholes_price(
            current_price * 0.85, long_strike, T_long, 0.05, 0.70, "call"
        )
        long_value_up_10 = black_scholes_price(
            current_price * 1.10, long_strike, T_long, 0.05, 0.50, "call"
        )

    unprotected_loss_10 = (long_value_now - long_value_down_10) * long_qty * 100
    unprotected_loss_15 = (long_value_now - long_value_down_15) * long_qty * 100
    unprotected_gain_10 = (long_value_up_10 - long_value_now) * long_qty * 100

    return {
        "symbol": symbol,
        "current_price": current_price,
        "long_strike": long_strike,
        "long_expiry": long_expiry,
        "long_qty": long_qty,
        "long_cost": long_cost,
        "long_value_now": long_value_now,
        "short_positions": short_positions,
        "is_proper_pmcc": is_proper_pmcc,
        "short_above_long": short_above_long,
        "earnings_date": earnings_date,
        "days_to_earnings": days_to_earnings,
        "put_analysis": put_analysis,
        "unprotected_loss_10": unprotected_loss_10,
        "unprotected_loss_15": unprotected_loss_15,
        "unprotected_gain_10": unprotected_gain_10,
        "volatility": volatility,
    }


def generate_pdf_report(analysis: dict, output_path: Path) -> None:
    """Generate PDF report for the collar analysis."""
    try:
        from fpdf import FPDF
    except ImportError:
        print("Warning: fpdf2 not installed. Generating markdown only.")
        generate_markdown_report(analysis, output_path.with_suffix(".md"))
        return

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, f"{analysis['symbol']} Tactical Collar Strategy Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    pdf.ln(5)

    # Position Summary
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Position Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)

    pdf.cell(60, 6, f"Symbol: {analysis['symbol']}", ln=False)
    pdf.cell(60, 6, f"Current Price: ${analysis['current_price']:.2f}", ln=False)
    pdf.cell(60, 6, f"Long Qty: {analysis['long_qty']} contracts", ln=True)

    pdf.cell(60, 6, f"Long Strike: ${analysis['long_strike']:.0f}", ln=False)
    pdf.cell(60, 6, f"Long Expiry: {analysis['long_expiry']}", ln=False)
    pdf.cell(60, 6, f"Long Cost: ${analysis['long_cost']:.2f}/contract", ln=True)

    total_investment = analysis["long_cost"] * analysis["long_qty"] * 100
    current_value = analysis["long_value_now"] * analysis["long_qty"] * 100
    pdf.cell(60, 6, f"Total Investment: ${total_investment:,.0f}", ln=False)
    pdf.cell(60, 6, f"Current Value: ${current_value:,.0f}", ln=True)
    pdf.ln(3)

    # PMCC Health Check
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "PMCC Health Check", ln=True)
    pdf.set_font("Helvetica", "", 10)

    if analysis["is_proper_pmcc"] and analysis["short_above_long"]:
        status = "[OK] Proper PMCC - Long is near/ITM, shorts above long strike"
    elif analysis["short_above_long"]:
        status = "[!] Long is OTM but shorts are above long strike - monitor closely"
    else:
        status = "[!!] BROKEN PMCC - Shorts below long strike require margin"
    pdf.cell(0, 6, status, ln=True)

    if analysis["short_positions"]:
        pdf.cell(0, 6, "Short Positions:", ln=True)
        for sp in analysis["short_positions"]:
            pdf.cell(
                0, 5, f"  - {sp['qty']}x ${sp['strike']:.0f} calls exp {sp['expiry']}", ln=True
            )
    pdf.ln(3)

    # Earnings Risk
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Earnings Risk Assessment", ln=True)
    pdf.set_font("Helvetica", "", 10)

    if analysis["earnings_date"]:
        pdf.cell(0, 6, f"Next Earnings: {analysis['earnings_date'].strftime('%Y-%m-%d')}", ln=True)
        pdf.cell(0, 6, f"Days Until Earnings: {analysis['days_to_earnings']}", ln=True)

        if analysis["days_to_earnings"] <= 7:
            risk_level = "[!!] CRITICAL - Earnings within 1 week"
        elif analysis["days_to_earnings"] <= 14:
            risk_level = "[!] WARNING - Earnings within 2 weeks"
        elif analysis["days_to_earnings"] <= 30:
            risk_level = "[?] MONITOR - Earnings within 1 month"
        else:
            risk_level = "[OK] Earnings more than 30 days out"
        pdf.cell(0, 6, risk_level, ln=True)
    else:
        pdf.cell(0, 6, "No upcoming earnings date found", ln=True)

    pdf.cell(
        0, 6, f"Unprotected Gain (10% gap up): ${analysis['unprotected_gain_10']:,.0f}", ln=True
    )
    pdf.cell(
        0, 6, f"Unprotected Loss (10% gap down): ${analysis['unprotected_loss_10']:,.0f}", ln=True
    )
    pdf.cell(
        0, 6, f"Unprotected Loss (15% gap down): ${analysis['unprotected_loss_15']:,.0f}", ln=True
    )
    pdf.ln(3)

    # Put Duration Analysis
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Put Protection Analysis", ln=True)
    pdf.set_font("Helvetica", "", 10)

    if not analysis["put_analysis"]:
        pdf.cell(0, 6, "No suitable put options found for analysis", ln=True)
    else:
        expiries_shown = set()
        for pa in analysis["put_analysis"]:
            if pa["expiry"] in expiries_shown:
                continue
            expiries_shown.add(pa["expiry"])

            pdf.set_font("Helvetica", "B", 11)
            days_after = (
                f" ({pa['days_after_earnings']} days after earnings)"
                if pa["days_after_earnings"]
                else ""
            )
            pdf.cell(
                0, 7, f"Expiry: {pa['expiry']} - {pa['days_out']} days out{days_after}", ln=True
            )
            pdf.set_font("Helvetica", "", 9)

            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(25, 5, "Strike", border=1, align="C")
            pdf.cell(20, 5, "OTM %", border=1, align="C")
            pdf.cell(25, 5, "Cost", border=1, align="C")
            pdf.cell(30, 5, "Gap Up 10%", border=1, align="C")
            pdf.cell(30, 5, "Flat", border=1, align="C")
            pdf.cell(30, 5, "Gap Dn 10%", border=1, align="C")
            pdf.cell(30, 5, "Gap Dn 15%", border=1, align="C")
            pdf.ln()

            pdf.set_font("Helvetica", "", 9)
            for pa2 in analysis["put_analysis"]:
                if pa2["expiry"] != pa["expiry"]:
                    continue
                pdf.cell(25, 5, f"${pa2['strike']:.0f}", border=1, align="C")
                pdf.cell(20, 5, f"{pa2['otm_pct']:.0f}%", border=1, align="C")
                pdf.cell(25, 5, f"${pa2['total_cost']:,.0f}", border=1, align="C")
                pdf.cell(
                    30, 5, f"${pa2['scenarios']['gap_up_10']['put_pnl']:+,.0f}", border=1, align="C"
                )
                pdf.cell(
                    30, 5, f"${pa2['scenarios']['flat']['put_pnl']:+,.0f}", border=1, align="C"
                )
                pdf.cell(
                    30,
                    5,
                    f"${pa2['scenarios']['gap_down_10']['put_pnl']:+,.0f}",
                    border=1,
                    align="C",
                )
                pdf.cell(
                    30,
                    5,
                    f"${pa2['scenarios']['gap_down_15']['put_pnl']:+,.0f}",
                    border=1,
                    align="C",
                )
                pdf.ln()
            pdf.ln(2)

    # Recommendation
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Recommendation", ln=True)
    pdf.set_font("Helvetica", "", 10)

    best_put = None
    for pa in analysis["put_analysis"]:
        if pa["days_after_earnings"] and 5 <= pa["days_after_earnings"] <= 25:
            gap_15_pnl = pa["scenarios"]["gap_down_15"]["put_pnl"]
            if best_put is None:
                best_put = pa
            elif gap_15_pnl > best_put["scenarios"]["gap_down_15"]["put_pnl"]:
                best_put = pa

    if not best_put and analysis["put_analysis"]:
        best_put = max(
            analysis["put_analysis"], key=lambda p: p["scenarios"]["gap_down_15"]["put_pnl"]
        )

    if best_put:
        pdf.cell(
            0, 6, f"Recommended Put: {best_put['expiry']} ${best_put['strike']:.0f} put", ln=True
        )
        pdf.cell(
            0,
            6,
            f"  - Cost: ${best_put['total_cost']:,.0f} ({best_put['otm_pct']:.0f}% OTM)",
            ln=True,
        )
        dn10 = format_pnl(best_put['scenarios']['gap_down_10']['put_pnl'])
        dn15 = format_pnl(best_put['scenarios']['gap_down_15']['put_pnl'])
        up10 = format_pnl(best_put['scenarios']['gap_up_10']['put_pnl'])
        pdf.cell(0, 6, f"  - If gap down 10%: Put {dn10}", ln=True)
        pdf.cell(0, 6, f"  - If gap down 15%: Put {dn15}", ln=True)
        pdf.cell(0, 6, f"  - If gap up 10%: Put {up10}", ln=True)
        pdf.ln(3)

        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, "Net Position with Protection:", ln=True)
        pdf.set_font("Helvetica", "", 10)

        for scenario, label in [
            ("gap_down_15", "Gap Down 15%"),
            ("gap_down_10", "Gap Down 10%"),
            ("gap_up_10", "Gap Up 10%"),
        ]:
            if scenario.startswith("gap_down"):
                pct = scenario.split('_')[-1]
                long_loss = analysis[f"unprotected_loss_{pct}"]
                put_gain = best_put["scenarios"][scenario]["put_pnl"]
                net = -long_loss + put_gain
                text = (
                    f"  {label}: Long loses ${long_loss:,.0f},"
                    f" Put gains ${put_gain:+,.0f},"
                    f" Net: ${net:+,.0f}"
                )
                pdf.cell(0, 5, text, ln=True)
            else:
                long_gain = analysis["unprotected_gain_10"]
                put_pnl = best_put["scenarios"][scenario]["put_pnl"]
                net = long_gain + put_pnl
                pnl_str = format_pnl(put_pnl)
                text = (
                    f"  {label}: Long gains ${long_gain:,.0f},"
                    f" Put {pnl_str},"
                    f" Net: ${net:+,.0f}"
                )
                pdf.cell(0, 5, text, ln=True)

    pdf.ln(5)

    # Implementation Timeline
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Implementation Timeline", ln=True)
    pdf.set_font("Helvetica", "", 10)

    if analysis["earnings_date"] and analysis["days_to_earnings"]:
        earnings = analysis["earnings_date"]
        buy_puts_date = earnings - timedelta(days=min(14, analysis["days_to_earnings"] - 1))
        close_shorts_date = earnings - timedelta(days=2)

        pdf.cell(0, 6, f"[ ] {buy_puts_date.strftime('%Y-%m-%d')}: Buy protective puts", ln=True)

        for sp in analysis["short_positions"]:
            sp_expiry = datetime.strptime(sp["expiry"], "%Y%m%d")
            if sp_expiry > earnings:
                close_date = close_shorts_date.strftime('%Y-%m-%d')
                qty = sp['qty']
                strike = sp['strike']
                text = (
                    f"[ ] {close_date}: Close/roll"
                    f" {qty}x ${strike:.0f} shorts"
                    f" (expire after earnings)"
                )
                pdf.cell(0, 6, text, ln=True)

        earn_date = earnings.strftime('%Y-%m-%d')
        day1 = (earnings + timedelta(days=1)).strftime('%Y-%m-%d')
        day2 = (earnings + timedelta(days=2)).strftime('%Y-%m-%d')
        pdf.cell(
            0, 6,
            f"[ ] {earn_date}: EARNINGS - Position protected",
            ln=True,
        )
        pdf.cell(
            0, 6,
            f"[ ] {day1}: Evaluate position, sell puts if gap up",
            ln=True,
        )
        pdf.cell(
            0, 6,
            f"[ ] {day2}: Resume normal PMCC (sell new short calls)",
            ln=True,
        )
    else:
        pdf.cell(0, 6, "No specific timeline - no earnings date found", ln=True)

    pdf.ln(5)

    # Key Insights
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "Key Insights", ln=True)
    pdf.set_font("Helvetica", "", 10)

    insights = [
        "Short-dated puts (weekly): Cheaper, more gamma on crash, but zero salvage on gap up",
        "Medium-dated puts (2-4 weeks after event): Best balance of cost, gamma, and salvage value",
        "Long-dated puts (60+ days): Preserves value on gap up, but expensive and less gamma",
        "Recommendation: Buy puts 1-2 weeks before earnings, choose expiry 1-3 weeks after",
        "After earnings: Sell puts immediately (take profit or accept IV crush loss)",
    ]

    for insight in insights:
        pdf.cell(0, 5, f"* {insight}", ln=True)

    pdf.output(str(output_path))
    print(f"Report saved to: {output_path}")


def generate_markdown_report(analysis: dict, output_path: Path) -> None:
    """Generate comprehensive markdown report."""
    lines = [
        f"# {analysis['symbol']} Tactical Collar Strategy Report",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        "## Position Summary",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Symbol | {analysis['symbol']} |",
        f"| Current Price | ${analysis['current_price']:.2f} |",
        f"| Long Position | {analysis['long_qty']}x ${analysis['long_strike']:.0f} calls |",
        f"| Long Expiry | {analysis['long_expiry']} |",
        f"| Long Cost | ${analysis['long_cost']:.2f}/contract |",
        f"| Total Investment | ${analysis['long_cost'] * analysis['long_qty'] * 100:,.0f} |",
        f"| Current Value | ${analysis['long_value_now'] * analysis['long_qty'] * 100:,.0f} |",
        "",
        "## PMCC Health Check",
        "",
    ]

    if analysis["is_proper_pmcc"] and analysis["short_above_long"]:
        lines.append("**[OK]** Proper PMCC - Long is near/ITM, shorts above long strike")
    elif analysis["short_above_long"]:
        lines.append("**[!]** Long is OTM but shorts are above long strike - monitor closely")
    else:
        lines.append("**[!!]** BROKEN PMCC - Shorts below long strike require margin")

    lines.append("")

    if analysis["short_positions"]:
        lines.append("**Short Positions:**")
        for sp in analysis["short_positions"]:
            lines.append(f"- {sp['qty']}x ${sp['strike']:.0f} calls exp {sp['expiry']}")
        lines.append("")

    # Earnings Risk
    lines.extend(
        [
            "## Earnings Risk Assessment",
            "",
        ]
    )

    if analysis["earnings_date"]:
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| Next Earnings | {analysis['earnings_date'].strftime('%Y-%m-%d')} |")
        lines.append(f"| Days Until Earnings | {analysis['days_to_earnings']} |")

        if analysis["days_to_earnings"] <= 7:
            risk_level = "**[!!] CRITICAL** - Earnings within 1 week"
        elif analysis["days_to_earnings"] <= 14:
            risk_level = "**[!] WARNING** - Earnings within 2 weeks"
        elif analysis["days_to_earnings"] <= 30:
            risk_level = "**[?] MONITOR** - Earnings within 1 month"
        else:
            risk_level = "**[OK]** - Earnings more than 30 days out"
        lines.append(f"| Risk Level | {risk_level} |")
        lines.append(f"| Unprotected Gain (10% gap up) | ${analysis['unprotected_gain_10']:,.0f} |")
        lines.append(
            f"| Unprotected Loss (10% gap down) | ${analysis['unprotected_loss_10']:,.0f} |"
        )
        lines.append(
            f"| Unprotected Loss (15% gap down) | ${analysis['unprotected_loss_15']:,.0f} |"
        )
    else:
        lines.append("No upcoming earnings date found.")

    lines.extend(["", "## Put Protection Analysis", ""])

    if not analysis["put_analysis"]:
        lines.append("No suitable put options found for analysis.")
    else:
        expiries_shown = set()
        for pa in analysis["put_analysis"]:
            if pa["expiry"] in expiries_shown:
                continue
            expiries_shown.add(pa["expiry"])

            days_after = (
                f" ({pa['days_after_earnings']} days after earnings)"
                if pa["days_after_earnings"]
                else ""
            )
            lines.extend(
                [
                    f"### Expiry: {pa['expiry']} - {pa['days_out']} days out{days_after}",
                    "",
                    "| Strike | OTM % | Cost | Gap Up 10% | Flat | Gap Dn 10% | Gap Dn 15% |",
                    "|--------|-------|------|------------|------|------------|------------|",
                ]
            )

            for pa2 in analysis["put_analysis"]:
                if pa2["expiry"] != pa["expiry"]:
                    continue
                lines.append(
                    f"| ${pa2['strike']:.0f} | {pa2['otm_pct']:.0f}% | ${pa2['total_cost']:,.0f} | "
                    f"${pa2['scenarios']['gap_up_10']['put_pnl']:+,.0f} | "
                    f"${pa2['scenarios']['flat']['put_pnl']:+,.0f} | "
                    f"${pa2['scenarios']['gap_down_10']['put_pnl']:+,.0f} | "
                    f"${pa2['scenarios']['gap_down_15']['put_pnl']:+,.0f} |"
                )
            lines.append("")

    # Net Position Summary Table
    if analysis["put_analysis"]:
        unprotected_10 = analysis["unprotected_loss_10"]
        unprotected_15 = analysis["unprotected_loss_15"]
        unprotected_gain = analysis["unprotected_gain_10"]

        lines.extend(
            [
                "## Net Position Summary",
                "",
                "Combined long call + put P&L for each scenario:",
                "",
                "| Expiry | Strike | Cost | Gap Up 10% |"
                " Flat | Gap Dn 10% | Gap Dn 15% |",
                "|--------|--------|------|------------|"
                "------|------------|------------|",
                f"| **No Protection** | - | $0 |"
                f" **${unprotected_gain:+,.0f}** | $0 |"
                f" **${-unprotected_10:,.0f}** |"
                f" **${-unprotected_15:,.0f}** |",
            ]
        )

        for pa in analysis["put_analysis"]:
            net_up = unprotected_gain + pa["scenarios"]["gap_up_10"]["put_pnl"]
            net_flat = pa["scenarios"]["flat"]["put_pnl"]
            net_dn_10 = -unprotected_10 + pa["scenarios"]["gap_down_10"]["put_pnl"]
            net_dn_15 = -unprotected_15 + pa["scenarios"]["gap_down_15"]["put_pnl"]

            lines.append(
                f"| {pa['expiry']} | ${pa['strike']:.0f} | ${pa['total_cost']:,.0f} | "
                f"${net_up:+,.0f} | ${net_flat:+,.0f} | ${net_dn_10:+,.0f} | ${net_dn_15:+,.0f} |"
            )

        best_15 = max(
            analysis["put_analysis"],
            key=lambda p: -unprotected_15 + p["scenarios"]["gap_down_15"]["put_pnl"],
        )
        best_net_15 = -unprotected_15 + best_15["scenarios"]["gap_down_15"]["put_pnl"]
        savings = unprotected_15 - abs(best_net_15)

        lines.extend(
            [
                "",
                f"**Best protection on 15% gap:**"
                f" {best_15['expiry']}"
                f" ${best_15['strike']:.0f} put -"
                f" saves ${savings:,.0f} vs unprotected"
                f" (${best_net_15:,.0f}"
                f" vs ${-unprotected_15:,.0f})",
                "",
            ]
        )

    # Volatility and Timing Analysis
    vol = analysis.get("volatility", {})
    if vol and "error" not in vol:
        current_price = analysis["current_price"]

        lines.extend(
            [
                "## Volatility & Timing Analysis",
                "",
                f"**Stock Volatility:** {vol['vol_class']}"
                f" ({vol['annual_vol_pct']:.0f}% annualized)",
                "",
                "### Expected Price Movement Before Earnings",
                "",
                "| Time Period | Expected Move (1 SD)"
                " | Price Range |",
                "|-------------|---------------------"
                "|-------------|",
            ]
        )

        m1w = vol['move_1_week']
        m2w = vol['move_2_weeks']
        m3w = vol['move_3_weeks']
        lines.extend(
            [
                f"| 1 Week | +/-${m1w:.2f}"
                f" ({vol['move_1_week_pct']:.1f}%)"
                f" | ${current_price - m1w:.2f}"
                f" - ${current_price + m1w:.2f} |",
                f"| 2 Weeks | +/-${m2w:.2f}"
                f" ({vol['move_2_weeks_pct']:.1f}%)"
                f" | ${current_price - m2w:.2f}"
                f" - ${current_price + m2w:.2f} |",
                f"| 3 Weeks | +/-${m3w:.2f}"
                f" ({vol['move_3_weeks_pct']:.1f}%)"
                f" | ${current_price - m3w:.2f}"
                f" - ${current_price + m3w:.2f} |",
                "",
            ]
        )

        if vol["vol_class"] in ["EXTREME", "VERY HIGH"]:
            timing_rec = "**BUY DAY BEFORE EARNINGS** - Stock moves too much to buy early"
            move_pct = vol['move_2_weeks_pct']
            timing_reason = (
                f"With {vol['vol_class']} volatility,"
                f" stock could move {move_pct:.0f}%"
                f" before earnings. Buying early risks:\n"
                f"- Put strike becoming wrong (too far OTM if stock rallies)\n"
                f"- Significant theta + delta decay\n"
                f"- Having to buy a second put at the right strike"
            )
            lines.extend(
                [
                    f"### Timing Recommendation: {timing_rec}",
                    "",
                    timing_reason,
                    "",
                    "### Day-Before Strike Selection Guide",
                    "",
                    "On the day before earnings, select put strike"
                    " based on where stock is trading:",
                    "",
                    "| If Stock Price Is | Recommended Strike (5-7% OTM) |",
                    "|-------------------|-------------------------------|",
                ]
            )
            for pct in [-15, -10, -5, 0, 5, 10, 15]:
                future_price = current_price * (1 + pct / 100)
                strike_5 = round(future_price * 0.95 / 5) * 5
                strike_7 = round(future_price * 0.93 / 5) * 5
                lines.append(
                    f"| ${future_price:.0f} ({pct:+d}% from today)"
                    f" | ${strike_7:.0f} - ${strike_5:.0f} |"
                )
            lines.append("")

        elif vol["vol_class"] == "HIGH":
            timing_rec = "**BUY 3-5 DAYS BEFORE** - Balance timing vs. cost"
            lines.extend(
                [
                    f"### Timing Recommendation: {timing_rec}",
                    "",
                    f"With HIGH volatility"
                    f" ({vol['annual_vol_pct']:.0f}%),"
                    f" buying too early risks"
                    f" {vol['move_2_weeks_pct']:.0f}% move"
                    f" before earnings."
                    f" Wait until closer to the event.",
                    "",
                ]
            )
        else:
            timing_rec = "**BUY 1-2 WEEKS BEFORE** - Lower volatility allows early purchase"
            lines.extend(
                [
                    f"### Timing Recommendation: {timing_rec}",
                    "",
                    f"With {vol['vol_class']} volatility ({vol['annual_vol_pct']:.0f}%), "
                    f"stock is unlikely to move significantly before earnings. "
                    f"Buying early locks in lower IV premium.",
                    "",
                ]
            )

        lines.extend(
            [
                "### IV Premium Warning",
                "",
                "Puts bought day before earnings will cost ~30-50% more due to elevated IV.",
                "However, for high-volatility stocks, this is often worth it to:",
                "- Know exact strike needed",
                "- Avoid theta decay",
                "- Avoid delta loss if stock moves against you",
                "",
            ]
        )

    # Recommendation
    lines.extend(["## Recommendation", ""])

    best_put = None
    for pa in analysis["put_analysis"]:
        if pa["days_after_earnings"] and 5 <= pa["days_after_earnings"] <= 25:
            gap_15_pnl = pa["scenarios"]["gap_down_15"]["put_pnl"]
            if best_put is None:
                best_put = pa
            elif gap_15_pnl > best_put["scenarios"]["gap_down_15"]["put_pnl"]:
                best_put = pa

    if not best_put and analysis["put_analysis"]:
        best_put = max(
            analysis["put_analysis"], key=lambda p: p["scenarios"]["gap_down_15"]["put_pnl"]
        )

    if best_put:
        lines.extend(
            [
                f"**Recommended Put:** {best_put['expiry']} ${best_put['strike']:.0f} put",
                "",
                "| Scenario | Outcome |",
                "|----------|---------|",
                f"| Cost | ${best_put['total_cost']:,.0f}"
                f" ({best_put['otm_pct']:.0f}% OTM) |",
                f"| Gap Down 10% | Put"
                f" {format_pnl(best_put['scenarios']['gap_down_10']['put_pnl'])}"
                f" |",
                f"| Gap Down 15% | Put"
                f" {format_pnl(best_put['scenarios']['gap_down_15']['put_pnl'])}"
                f" |",
                f"| Gap Up 10% | Put"
                f" {format_pnl(best_put['scenarios']['gap_up_10']['put_pnl'])}"
                f" |",
                "",
                "### Net Position with Protection",
                "",
            ]
        )

        for scenario, label in [
            ("gap_down_15", "Gap Down 15%"),
            ("gap_down_10", "Gap Down 10%"),
            ("gap_up_10", "Gap Up 10%"),
        ]:
            if scenario.startswith("gap_down"):
                pct = "15" if "15" in scenario else "10"
                long_loss = analysis[f"unprotected_loss_{pct}"]
                put_pnl = best_put["scenarios"][scenario]["put_pnl"]
                net = -long_loss + put_pnl
                pnl_str = format_pnl(put_pnl)
                lines.append(
                    f"- **{label}:** Long loses"
                    f" ${long_loss:,.0f},"
                    f" Put {pnl_str},"
                    f" **Net: ${net:+,.0f}**"
                )
            else:
                long_gain = analysis["unprotected_gain_10"]
                put_pnl = best_put["scenarios"][scenario]["put_pnl"]
                net = long_gain + put_pnl
                pnl_str = format_pnl(put_pnl)
                lines.append(
                    f"- **{label}:** Long gains"
                    f" ${long_gain:,.0f},"
                    f" Put {pnl_str},"
                    f" **Net: ${net:+,.0f}**"
                )

        lines.append("")

    # Implementation Timeline
    lines.extend(["## Implementation Timeline", ""])

    if analysis["earnings_date"] and analysis["days_to_earnings"]:
        earnings = analysis["earnings_date"]
        buy_puts_date = earnings - timedelta(days=min(14, analysis["days_to_earnings"] - 1))
        close_shorts_date = earnings - timedelta(days=2)

        lines.append(f"- [ ] **{buy_puts_date.strftime('%Y-%m-%d')}:** Buy protective puts")

        for sp in analysis["short_positions"]:
            sp_expiry = datetime.strptime(sp["expiry"], "%Y%m%d")
            if sp_expiry > earnings:
                close_date = close_shorts_date.strftime('%Y-%m-%d')
                qty = sp['qty']
                strike = sp['strike']
                lines.append(
                    f"- [ ] **{close_date}:** Close/roll"
                    f" {qty}x ${strike:.0f} shorts"
                    f" (expire after earnings)"
                )

        earn_date = earnings.strftime('%Y-%m-%d')
        day1 = (earnings + timedelta(days=1)).strftime('%Y-%m-%d')
        day2 = (earnings + timedelta(days=2)).strftime('%Y-%m-%d')
        lines.extend(
            [
                f"- [ ] **{earn_date}:** EARNINGS"
                f" - Position protected",
                f"- [ ] **{day1}:** Evaluate"
                f" position, sell puts if gap up",
                f"- [ ] **{day2}:** Resume normal"
                f" PMCC (sell new short calls)",
            ]
        )
    else:
        lines.append("No specific timeline - no earnings date found.")

    lines.extend(
        [
            "",
            "## Key Insights",
            "",
            "- **Short-dated puts (weekly):** Cheaper, more gamma on crash,"
            " but zero salvage on gap up",
            "- **Medium-dated puts (2-4 weeks):**"
            " Best balance of cost, gamma, and salvage value",
            "- **Long-dated puts (60+ days):** Preserves value on gap up,"
            " but expensive and less gamma",
            "- **Recommendation:** Buy puts 1-2 weeks before earnings,"
            " choose expiry 1-3 weeks after",
            "- **After earnings:** Sell puts immediately (take profit or accept IV crush loss)",
            "",
        ]
    )

    output_path.write_text("\n".join(lines))
    print(f"Markdown report saved to: {output_path}")


async def get_portfolio_positions(
    port: int, account: str | None
) -> tuple[bool, list[dict], str | None]:
    """Fetch portfolio positions from IB."""
    ib = IB()

    try:
        await ib.connectAsync(host="127.0.0.1", port=port, clientId=1)
    except Exception as e:
        return False, [], f"Could not connect to IB on port {port}: {e}"

    try:
        await asyncio.sleep(2)

        managed = ib.managedAccounts()
        if account:
            if account not in managed:
                return True, [], f"Account {account} not found. Available: {managed}"
            accounts = [account]
        else:
            accounts = managed

        positions = []
        for acct in accounts:
            for pos in ib.positions(account=acct):
                contract = pos.contract
                entry = {
                    "account": pos.account,
                    "symbol": contract.symbol,
                    "sec_type": contract.secType,
                    "quantity": pos.position,
                    "avg_cost": pos.avgCost,
                }
                if contract.secType == "OPT":
                    multiplier = int(contract.multiplier) if contract.multiplier else 100
                    entry.update(
                        {
                            "strike": contract.strike,
                            "expiry": contract.lastTradeDateOrContractMonth,
                            "right": contract.right,
                            "avg_cost": pos.avgCost / multiplier,
                        }
                    )
                positions.append(entry)

        # Get current prices for underlyings
        symbols = {p["symbol"] for p in positions if p["sec_type"] == "OPT"}
        prices = {}

        if symbols:
            contracts = [Stock(sym, "SMART", "USD") for sym in symbols]
            try:
                qualified = await asyncio.wait_for(ib.qualifyContractsAsync(*contracts), timeout=15)
                tickers = await asyncio.wait_for(ib.reqTickersAsync(*qualified), timeout=15)
                for t in tickers:
                    p = t.marketPrice()
                    if p and p > 0:
                        prices[t.contract.symbol] = p
            except asyncio.TimeoutError:
                pass

        # Add prices to positions
        for pos in positions:
            if pos["symbol"] in prices:
                pos["underlying_price"] = prices[pos["symbol"]]

        return True, positions, None

    finally:
        ib.disconnect()

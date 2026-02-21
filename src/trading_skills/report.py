# ABOUTME: Gathers comprehensive stock analysis data from multiple modules.
# ABOUTME: Returns detailed JSON for PDF generation by Claude.

from datetime import datetime, timedelta

import yfinance as yf

from trading_skills.fundamentals import get_fundamentals
from trading_skills.piotroski import calculate_piotroski_score
from trading_skills.scanner_bullish import compute_bullish_score
from trading_skills.scanner_pmcc import analyze_pmcc
from trading_skills.spreads import get_option_price
from trading_skills.utils import get_current_price


def analyze_spreads(symbol: str) -> dict:
    """Analyze various option spread strategies for the symbol."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        price = get_current_price(info)

        if not price:
            return {"error": "Could not get current price"}

        # Get available expiries
        expiries = ticker.options
        if not expiries:
            return {"error": "No options available"}

        # Find expiry ~30-45 days out
        today = datetime.now().date()
        target_date = today + timedelta(days=35)
        selected_expiry = None

        for exp in expiries:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            if exp_date >= target_date:
                selected_expiry = exp
                break

        if not selected_expiry:
            selected_expiry = expiries[-1] if expiries else None

        if not selected_expiry:
            return {"error": "No suitable expiry found"}

        # Get option chain
        chain = ticker.option_chain(selected_expiry)
        calls = chain.calls
        puts = chain.puts

        if calls.empty or puts.empty:
            return {"error": "Empty option chain"}

        # Find ATM strike (closest to current price)
        strikes = sorted(calls["strike"].unique())
        atm_strike = min(strikes, key=lambda x: abs(x - price))

        # Find strike increment
        strike_diff = strikes[1] - strikes[0] if len(strikes) > 1 else 5

        # Calculate days to expiry
        exp_date = datetime.strptime(selected_expiry, "%Y-%m-%d").date()
        dte = (exp_date - today).days

        results = {
            "expiry": selected_expiry,
            "dte": dte,
            "underlying_price": round(price, 2),
            "atm_strike": atm_strike,
            "strategies": {},
        }

        def get_option(option_type, strike):
            opt = get_option_price(calls, puts, strike, option_type)
            if opt is None:
                return None
            opt["iv"] = round(opt["iv"] * 100, 1)
            return opt

        # 1. Bull Call Spread (ATM / ATM+1)
        long_strike = atm_strike
        short_strike = atm_strike + strike_diff
        long_call = get_option("call", long_strike)
        short_call = get_option("call", short_strike)

        if long_call and short_call:
            net_debit = long_call["mid"] - short_call["mid"]
            width = short_strike - long_strike
            max_profit = width - net_debit
            results["strategies"]["bull_call_spread"] = {
                "name": "Bull Call Spread",
                "direction": "bullish",
                "long_strike": long_strike,
                "short_strike": short_strike,
                "net_debit": round(net_debit, 2),
                "net_debit_total": round(net_debit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(net_debit * 100, 2),
                "breakeven": round(long_strike + net_debit, 2),
                "risk_reward": round(max_profit / net_debit, 2) if net_debit > 0 else None,
            }

        # 2. Bear Put Spread (ATM / ATM-1)
        long_strike = atm_strike
        short_strike = atm_strike - strike_diff
        long_put = get_option("put", long_strike)
        short_put = get_option("put", short_strike)

        if long_put and short_put:
            net_debit = long_put["mid"] - short_put["mid"]
            width = long_strike - short_strike
            max_profit = width - net_debit
            results["strategies"]["bear_put_spread"] = {
                "name": "Bear Put Spread",
                "direction": "bearish",
                "long_strike": long_strike,
                "short_strike": short_strike,
                "net_debit": round(net_debit, 2),
                "net_debit_total": round(net_debit * 100, 2),
                "max_profit": round(max_profit * 100, 2),
                "max_loss": round(net_debit * 100, 2),
                "breakeven": round(long_strike - net_debit, 2),
                "risk_reward": round(max_profit / net_debit, 2) if net_debit > 0 else None,
            }

        # 3. Long Straddle (ATM call + ATM put)
        atm_call = get_option("call", atm_strike)
        atm_put = get_option("put", atm_strike)

        if atm_call and atm_put:
            total_cost = atm_call["mid"] + atm_put["mid"]
            results["strategies"]["long_straddle"] = {
                "name": "Long Straddle",
                "direction": "neutral (expects big move)",
                "strike": atm_strike,
                "call_cost": round(atm_call["mid"], 2),
                "put_cost": round(atm_put["mid"], 2),
                "total_cost": round(total_cost * 100, 2),
                "max_profit": "unlimited",
                "max_loss": round(total_cost * 100, 2),
                "breakeven_up": round(atm_strike + total_cost, 2),
                "breakeven_down": round(atm_strike - total_cost, 2),
                "move_needed_pct": round((total_cost / price) * 100, 1),
            }

        # 4. Long Strangle (OTM call + OTM put)
        call_strike = atm_strike + strike_diff
        put_strike = atm_strike - strike_diff
        otm_call = get_option("call", call_strike)
        otm_put = get_option("put", put_strike)

        if otm_call and otm_put:
            total_cost = otm_call["mid"] + otm_put["mid"]
            results["strategies"]["long_strangle"] = {
                "name": "Long Strangle",
                "direction": "neutral (expects big move)",
                "call_strike": call_strike,
                "put_strike": put_strike,
                "call_cost": round(otm_call["mid"], 2),
                "put_cost": round(otm_put["mid"], 2),
                "total_cost": round(total_cost * 100, 2),
                "max_profit": "unlimited",
                "max_loss": round(total_cost * 100, 2),
                "breakeven_up": round(call_strike + total_cost, 2),
                "breakeven_down": round(put_strike - total_cost, 2),
            }

        # 5. Iron Condor
        put_short = atm_strike - strike_diff
        put_long = atm_strike - 2 * strike_diff
        call_short = atm_strike + strike_diff
        call_long = atm_strike + 2 * strike_diff

        ic_put_short = get_option("put", put_short)
        ic_put_long = get_option("put", put_long)
        ic_call_short = get_option("call", call_short)
        ic_call_long = get_option("call", call_long)

        if all([ic_put_short, ic_put_long, ic_call_short, ic_call_long]):
            credit = (ic_put_short["mid"] + ic_call_short["mid"]) - (
                ic_put_long["mid"] + ic_call_long["mid"]
            )
            wing_width = strike_diff
            max_loss = wing_width - credit

            results["strategies"]["iron_condor"] = {
                "name": "Iron Condor",
                "direction": "neutral (expects low volatility)",
                "put_long": put_long,
                "put_short": put_short,
                "call_short": call_short,
                "call_long": call_long,
                "net_credit": round(credit, 2),
                "net_credit_total": round(credit * 100, 2),
                "max_profit": round(credit * 100, 2),
                "max_loss": round(max_loss * 100, 2),
                "breakeven_down": round(put_short - credit, 2),
                "breakeven_up": round(call_short + credit, 2),
                "profit_range": f"${put_short} - ${call_short}",
                "risk_reward": round(credit / max_loss, 2) if max_loss > 0 else None,
            }

        return results

    except Exception as e:
        return {"error": str(e)}


def fetch_data(symbol: str) -> dict:
    """Fetch all analysis data for a symbol using library functions directly."""
    # Bullish scanner
    bullish_data = compute_bullish_score(symbol) or {}

    # PMCC scanner
    pmcc_data = analyze_pmcc(symbol) or {}

    # Fundamentals
    fundamentals = get_fundamentals(symbol, "all")

    # Piotroski
    piotroski = calculate_piotroski_score(symbol)

    # Spread analysis
    spreads = analyze_spreads(symbol)

    return {
        "symbol": symbol,
        "bullish": bullish_data,
        "pmcc": pmcc_data,
        "fundamentals": fundamentals,
        "piotroski": piotroski,
        "spreads": spreads,
    }


def compute_recommendation(data: dict) -> dict:
    """Compute recommendation based on analysis data."""
    bullish = data.get("bullish", {})
    pmcc = data.get("pmcc", {})
    fundamentals = data.get("fundamentals", {})
    piotroski = data.get("piotroski", {})

    bullish_score = bullish.get("score", 0)
    pmcc_score = pmcc.get("pmcc_score", 0)

    info = fundamentals.get("info", {})
    forward_pe = info.get("forwardPE")

    points = 0
    strengths = []
    risks = []

    # Trend analysis
    if bullish_score >= 6:
        points += 2
        strengths.append(f"Strong bullish trend (score {bullish_score:.1f}/8)")
    elif bullish_score >= 4:
        points += 1
        strengths.append(f"Moderate bullish trend (score {bullish_score:.1f}/8)")
    else:
        risks.append(f"Weak/no trend (score {bullish_score:.1f}/8)")

    # PMCC viability
    if pmcc_score >= 9:
        points += 2
        strengths.append(f"Excellent PMCC candidate ({pmcc_score}/11)")
    elif pmcc_score >= 7:
        points += 1
        strengths.append(f"Good PMCC candidate ({pmcc_score}/11)")
    elif pmcc_score > 0:
        risks.append(f"Fair PMCC viability ({pmcc_score}/11)")

    # Valuation
    if forward_pe and forward_pe > 0:
        if forward_pe < 15:
            points += 1
            strengths.append(f"Attractive valuation (Fwd P/E {forward_pe:.1f}x)")
        elif forward_pe > 30:
            risks.append(f"Expensive valuation (Fwd P/E {forward_pe:.1f}x)")

    # RSI
    rsi = bullish.get("rsi", 50)
    if rsi > 70:
        risks.append(f"RSI overbought ({rsi:.1f})")
    elif rsi < 30:
        risks.append(f"RSI oversold ({rsi:.1f})")

    # Piotroski
    pio_score = piotroski.get("score", 0)
    if pio_score >= 7:
        points += 1
        strengths.append(f"Strong Piotroski score ({pio_score}/9)")
    elif pio_score <= 3:
        risks.append(f"Weak Piotroski score ({pio_score}/9)")

    # Additional strengths
    if bullish.get("adx", 0) >= 25:
        strengths.append(f"Confirmed trend (ADX {bullish.get('adx', 0):.1f})")
    if 25 <= pmcc.get("iv_pct", 0) <= 50:
        strengths.append(f"Ideal IV range ({pmcc.get('iv_pct', 0):.0f}%)")
    if (info.get("dividendYield") or 0) > 2:
        strengths.append(f"Attractive dividend ({info.get('dividendYield', 0):.1f}%)")
    if (info.get("returnOnEquity") or 0) > 0.15:
        strengths.append(f"Strong ROE ({info.get('returnOnEquity') * 100:.1f}%)")

    # Additional risks
    if (info.get("payoutRatio") or 0) > 0.8:
        risks.append(f"High payout ratio ({info.get('payoutRatio') * 100:.0f}%)")
    if (info.get("debtToEquity") or 0) > 100:
        risks.append(f"High debt/equity ({info.get('debtToEquity'):.0f}%)")
    if (info.get("revenueGrowth") or 0) < 0:
        risks.append(f"Revenue declining ({info.get('revenueGrowth') * 100:+.1f}%)")

    # Determine recommendation
    if points >= 4:
        recommendation = "BUY / PMCC CANDIDATE"
        recommendation_level = "positive"
    elif points >= 2:
        recommendation = "HOLD / MONITOR"
        recommendation_level = "neutral"
    else:
        recommendation = "AVOID / WAIT"
        recommendation_level = "negative"

    return {
        "recommendation": recommendation,
        "recommendation_level": recommendation_level,
        "points": points,
        "strengths": strengths,
        "risks": risks,
    }


def generate_report_data(symbol: str) -> dict:
    """Generate complete stock analysis report data."""
    symbol = symbol.upper()

    # Fetch data
    data = fetch_data(symbol)

    # Check if we got any data
    if not data.get("bullish") and not data.get("fundamentals"):
        return {"error": f"Failed to fetch data for {symbol}"}

    # Compute recommendation
    recommendation = compute_recommendation(data)

    return {
        "symbol": symbol,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "recommendation": recommendation,
        "company": {
            "name": data.get("fundamentals", {}).get("info", {}).get("name", symbol),
            "sector": data.get("fundamentals", {}).get("info", {}).get("sector"),
            "industry": data.get("fundamentals", {}).get("info", {}).get("industry"),
            "market_cap": data.get("fundamentals", {}).get("info", {}).get("marketCap"),
            "enterprise_value": data.get("fundamentals", {}).get("info", {}).get("enterpriseValue"),
            "beta": data.get("fundamentals", {}).get("info", {}).get("beta"),
        },
        "trend_analysis": {
            "bullish_score": data.get("bullish", {}).get("score"),
            "price": data.get("bullish", {}).get("price"),
            "period_return_pct": data.get("bullish", {}).get("period_return_pct"),
            "pct_from_sma20": data.get("bullish", {}).get("pct_from_sma20"),
            "pct_from_sma50": data.get("bullish", {}).get("pct_from_sma50"),
            "rsi": data.get("bullish", {}).get("rsi"),
            "macd": data.get("bullish", {}).get("macd"),
            "macd_signal": data.get("bullish", {}).get("macd_signal"),
            "adx": data.get("bullish", {}).get("adx"),
            "signals": data.get("bullish", {}).get("signals", []),
            "next_earnings": data.get("bullish", {}).get("next_earnings"),
            "earnings_timing": data.get("bullish", {}).get("earnings_timing"),
        },
        "pmcc_analysis": {
            "pmcc_score": data.get("pmcc", {}).get("pmcc_score"),
            "iv_pct": data.get("pmcc", {}).get("iv_pct"),
            "leaps": data.get("pmcc", {}).get("leaps", {}),
            "short": data.get("pmcc", {}).get("short", {}),
            "metrics": data.get("pmcc", {}).get("metrics", {}),
        },
        "fundamentals": {
            "valuation": {
                "trailing_pe": data.get("fundamentals", {}).get("info", {}).get("trailingPE"),
                "forward_pe": data.get("fundamentals", {}).get("info", {}).get("forwardPE"),
                "price_to_book": data.get("fundamentals", {}).get("info", {}).get("priceToBook"),
                "eps_ttm": data.get("fundamentals", {}).get("info", {}).get("eps"),
                "forward_eps": data.get("fundamentals", {}).get("info", {}).get("forwardEps"),
            },
            "profitability": {
                "profit_margin": data.get("fundamentals", {}).get("info", {}).get("profitMargin"),
                "operating_margin": data.get("fundamentals", {})
                .get("info", {})
                .get("operatingMargin"),
                "roe": data.get("fundamentals", {}).get("info", {}).get("returnOnEquity"),
                "roa": data.get("fundamentals", {}).get("info", {}).get("returnOnAssets"),
                "revenue_growth": data.get("fundamentals", {}).get("info", {}).get("revenueGrowth"),
                "earnings_growth": data.get("fundamentals", {})
                .get("info", {})
                .get("earningsGrowth"),
            },
            "dividend": {
                "yield": data.get("fundamentals", {}).get("info", {}).get("dividendYield"),
                "rate": data.get("fundamentals", {}).get("info", {}).get("dividendRate"),
                "payout_ratio": data.get("fundamentals", {}).get("info", {}).get("payoutRatio"),
            },
            "balance_sheet": {
                "debt_to_equity": data.get("fundamentals", {}).get("info", {}).get("debtToEquity"),
                "current_ratio": data.get("fundamentals", {}).get("info", {}).get("currentRatio"),
            },
            "earnings_history": data.get("fundamentals", {}).get("earnings", [])[:8],
        },
        "piotroski": {
            "score": data.get("piotroski", {}).get("score"),
            "max_score": 9,
            "interpretation": data.get("piotroski", {}).get("interpretation"),
            "criteria": data.get("piotroski", {}).get("criteria", {}),
        },
        "spread_strategies": data.get("spreads", {}),
    }

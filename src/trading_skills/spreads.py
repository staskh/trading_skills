# ABOUTME: Analyzes multi-leg option spread strategies.
# ABOUTME: Supports verticals, diagonals, straddles, strangles, iron condors.

import yfinance as yf

from trading_skills.utils import get_current_price


def get_option_price(chain_calls, chain_puts, strike: float, option_type: str) -> dict | None:
    """Get option price from chain."""
    options = chain_calls if option_type == "call" else chain_puts
    match = options[options["strike"] == strike]
    if match.empty:
        return None
    row = match.iloc[0]
    return {
        "strike": strike,
        "type": option_type,
        "bid": row.get("bid"),
        "ask": row.get("ask"),
        "mid": (row.get("bid", 0) + row.get("ask", 0)) / 2,
        "iv": row.get("impliedVolatility"),
    }


def analyze_vertical(
    symbol: str, expiry: str, option_type: str, long_strike: float, short_strike: float
) -> dict:
    """Analyze vertical spread (bull/bear call/put spread)."""
    ticker = yf.Ticker(symbol)
    chain = ticker.option_chain(expiry)
    info = ticker.info
    underlying = get_current_price(info)

    long_opt = get_option_price(chain.calls, chain.puts, long_strike, option_type)
    short_opt = get_option_price(chain.calls, chain.puts, short_strike, option_type)

    if not long_opt or not short_opt:
        return {"error": "Could not find options at specified strikes"}

    # Calculate spread metrics
    net_debit = long_opt["mid"] - short_opt["mid"]
    width = abs(long_strike - short_strike)

    if option_type == "call":
        if long_strike < short_strike:  # Bull call spread
            max_profit = width - net_debit
            max_loss = net_debit
            breakeven = long_strike + net_debit
            direction = "bullish"
        else:  # Bear call spread (credit spread)
            max_profit = -net_debit  # Credit received
            max_loss = width + net_debit
            breakeven = short_strike - net_debit
            direction = "bearish"
    else:  # put
        if long_strike > short_strike:  # Bear put spread
            max_profit = width - net_debit
            max_loss = net_debit
            breakeven = long_strike - net_debit
            direction = "bearish"
        else:  # Bull put spread (credit spread)
            max_profit = -net_debit
            max_loss = width + net_debit
            breakeven = short_strike + net_debit
            direction = "bullish"

    return {
        "symbol": symbol.upper(),
        "strategy": f"Vertical {option_type.title()} Spread",
        "direction": direction,
        "expiry": expiry,
        "underlying_price": round(underlying, 2),
        "legs": [
            {"action": "buy", **long_opt},
            {"action": "sell", **short_opt},
        ],
        "net_debit": round(net_debit, 2),
        "max_profit": round(max_profit * 100, 2),
        "max_loss": round(max_loss * 100, 2),
        "breakeven": round(breakeven, 2),
        "risk_reward": round(max_profit / max_loss, 2) if max_loss > 0 else None,
    }


def analyze_diagonal(
    symbol: str,
    option_type: str,
    long_expiry: str,
    long_strike: float,
    short_expiry: str,
    short_strike: float,
) -> dict:
    """Analyze diagonal spread (different expiries and strikes)."""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    underlying = get_current_price(info)

    # Get chains for both expiries
    long_chain = ticker.option_chain(long_expiry)
    short_chain = ticker.option_chain(short_expiry)

    long_opt = get_option_price(long_chain.calls, long_chain.puts, long_strike, option_type)
    short_opt = get_option_price(short_chain.calls, short_chain.puts, short_strike, option_type)

    if not long_opt or not short_opt:
        return {"error": "Could not find options at specified strikes/expiries"}

    # Calculate spread metrics
    net_debit = long_opt["mid"] - short_opt["mid"]

    # Determine direction
    if option_type == "call":
        if long_strike <= short_strike:
            direction = "bullish (poor man's covered call)"
        else:
            direction = "bearish"
    else:
        if long_strike >= short_strike:
            direction = "bearish (poor man's covered put)"
        else:
            direction = "bullish"

    short_credit = short_opt["mid"]

    return {
        "symbol": symbol.upper(),
        "strategy": f"Diagonal {option_type.title()} Spread",
        "direction": direction,
        "long_leg": {
            "action": "buy",
            "expiry": long_expiry,
            **long_opt,
        },
        "short_leg": {
            "action": "sell",
            "expiry": short_expiry,
            **short_opt,
        },
        "underlying_price": round(underlying, 2),
        "net_debit": round(net_debit, 2),
        "net_debit_total": round(net_debit * 100, 2),
        "max_loss": round(net_debit * 100, 2),
        "short_premium_collected": round(short_credit * 100, 2),
        "notes": "Max profit depends on IV at short expiry. Can sell again if short expires OTM.",
    }


def analyze_straddle(symbol: str, expiry: str, strike: float) -> dict:
    """Analyze long straddle (buy call + put at same strike)."""
    ticker = yf.Ticker(symbol)
    chain = ticker.option_chain(expiry)
    info = ticker.info
    underlying = get_current_price(info)

    call = get_option_price(chain.calls, chain.puts, strike, "call")
    put = get_option_price(chain.calls, chain.puts, strike, "put")

    if not call or not put:
        return {"error": "Could not find options at specified strike"}

    total_cost = call["mid"] + put["mid"]
    breakeven_up = strike + total_cost
    breakeven_down = strike - total_cost

    return {
        "symbol": symbol.upper(),
        "strategy": "Long Straddle",
        "direction": "neutral (expects big move)",
        "expiry": expiry,
        "underlying_price": round(underlying, 2),
        "legs": [
            {"action": "buy", **call},
            {"action": "buy", **put},
        ],
        "total_cost": round(total_cost * 100, 2),
        "max_profit": "unlimited",
        "max_loss": round(total_cost * 100, 2),
        "breakeven_up": round(breakeven_up, 2),
        "breakeven_down": round(breakeven_down, 2),
        "move_needed_pct": round((total_cost / strike) * 100, 2),
    }


def analyze_strangle(symbol: str, expiry: str, put_strike: float, call_strike: float) -> dict:
    """Analyze long strangle (buy OTM call + OTM put)."""
    ticker = yf.Ticker(symbol)
    chain = ticker.option_chain(expiry)
    info = ticker.info
    underlying = get_current_price(info)

    call = get_option_price(chain.calls, chain.puts, call_strike, "call")
    put = get_option_price(chain.calls, chain.puts, put_strike, "put")

    if not call or not put:
        return {"error": "Could not find options at specified strikes"}

    total_cost = call["mid"] + put["mid"]
    breakeven_up = call_strike + total_cost
    breakeven_down = put_strike - total_cost

    return {
        "symbol": symbol.upper(),
        "strategy": "Long Strangle",
        "direction": "neutral (expects big move)",
        "expiry": expiry,
        "underlying_price": round(underlying, 2),
        "legs": [
            {"action": "buy", **call},
            {"action": "buy", **put},
        ],
        "total_cost": round(total_cost * 100, 2),
        "max_profit": "unlimited",
        "max_loss": round(total_cost * 100, 2),
        "breakeven_up": round(breakeven_up, 2),
        "breakeven_down": round(breakeven_down, 2),
    }


def analyze_iron_condor(
    symbol: str, expiry: str, put_long: float, put_short: float, call_short: float, call_long: float
) -> dict:
    """Analyze iron condor (sell strangle + buy wider strangle for protection)."""
    ticker = yf.Ticker(symbol)
    chain = ticker.option_chain(expiry)
    info = ticker.info
    underlying = get_current_price(info)

    put_buy = get_option_price(chain.calls, chain.puts, put_long, "put")
    put_sell = get_option_price(chain.calls, chain.puts, put_short, "put")
    call_sell = get_option_price(chain.calls, chain.puts, call_short, "call")
    call_buy = get_option_price(chain.calls, chain.puts, call_long, "call")

    if not all([put_buy, put_sell, call_sell, call_buy]):
        return {"error": "Could not find options at all specified strikes"}

    # Net credit = sell premiums - buy premiums
    net_credit = (put_sell["mid"] + call_sell["mid"]) - (put_buy["mid"] + call_buy["mid"])

    # Max loss on either wing
    put_width = put_short - put_long
    call_width = call_long - call_short
    max_loss = max(put_width, call_width) - net_credit

    return {
        "symbol": symbol.upper(),
        "strategy": "Iron Condor",
        "direction": "neutral (expects low volatility)",
        "expiry": expiry,
        "underlying_price": round(underlying, 2),
        "legs": [
            {"action": "buy", **put_buy},
            {"action": "sell", **put_sell},
            {"action": "sell", **call_sell},
            {"action": "buy", **call_buy},
        ],
        "net_credit": round(net_credit * 100, 2),
        "max_profit": round(net_credit * 100, 2),
        "max_loss": round(max_loss * 100, 2),
        "breakeven_down": round(put_short - net_credit, 2),
        "breakeven_up": round(call_short + net_credit, 2),
        "profit_range": f"{put_short} - {call_short}",
    }

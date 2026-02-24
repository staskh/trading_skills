# ABOUTME: Finds roll options for short positions using real-time IBKR data.
# ABOUTME: Evaluates candidates, calculates roll credits/debits, and returns structured data.

import asyncio
import math
import sys
from datetime import datetime

from ib_async import IB, Option, Stock

from trading_skills.earnings import get_next_earnings_date
from trading_skills.utils import days_to_expiry


async def get_current_position(ib: IB, symbol: str, account: str = None) -> dict | None:
    """Find current short option position for symbol."""
    await asyncio.sleep(1)  # Allow data sync

    if account:
        positions = ib.positions(account=account)
    else:
        positions = ib.positions()

    # Find short option positions for this symbol
    short_options = []
    for pos in positions:
        c = pos.contract
        if c.symbol == symbol and c.secType == "OPT" and pos.position < 0:
            short_options.append(
                {
                    "account": pos.account,
                    "quantity": int(pos.position),
                    "strike": c.strike,
                    "expiry": c.lastTradeDateOrContractMonth,
                    "right": c.right,
                    "avg_cost": pos.avgCost / (int(c.multiplier) if c.multiplier else 100),
                }
            )

    if not short_options:
        return None

    # Show all found positions
    print(f"Found {len(short_options)} short {symbol} positions:", file=sys.stderr)
    for opt in short_options:
        qty = abs(opt['quantity'])
        acct = opt['account']
        s, r, e = opt['strike'], opt['right'], opt['expiry']
        print(
            f"  {acct}: -{qty} ${s} {r} exp {e}",
            file=sys.stderr,
        )

    # Return the nearest expiring short position
    short_options.sort(key=lambda x: x["expiry"])
    return short_options[0]


async def get_long_stock_position(ib: IB, symbol: str, account: str = None) -> dict | None:
    """Find long stock position for symbol."""
    if account:
        positions = ib.positions(account=account)
    else:
        positions = ib.positions()

    for pos in positions:
        c = pos.contract
        if c.symbol == symbol and c.secType == "STK" and pos.position > 0:
            return {
                "account": pos.account,
                "quantity": int(pos.position),
                "avg_cost": pos.avgCost,
            }

    return None


async def get_long_option_position(
    ib: IB, symbol: str, right: str = "C", account: str = None
) -> dict | None:
    """Find long option position for symbol."""
    if account:
        positions = ib.positions(account=account)
    else:
        positions = ib.positions()

    # Find long option positions for this symbol
    long_options = []
    for pos in positions:
        c = pos.contract
        if c.symbol == symbol and c.secType == "OPT" and pos.position > 0 and c.right == right:
            long_options.append(
                {
                    "account": pos.account,
                    "quantity": int(pos.position),
                    "strike": c.strike,
                    "expiry": c.lastTradeDateOrContractMonth,
                    "right": c.right,
                    "avg_cost": pos.avgCost / (int(c.multiplier) if c.multiplier else 100),
                }
            )

    if not long_options:
        return None

    # Show all found positions
    print(f"Found {len(long_options)} long {symbol} {right} positions:", file=sys.stderr)
    for opt in long_options:
        acct = opt['account']
        qty, s = opt['quantity'], opt['strike']
        r, e = opt['right'], opt['expiry']
        print(
            f"  {acct}: +{qty} ${s} {r} exp {e}",
            file=sys.stderr,
        )

    # Return the nearest expiring long position
    long_options.sort(key=lambda x: x["expiry"])
    return long_options[0]


async def get_underlying_price(ib: IB, symbol: str) -> float:
    """Get current underlying stock price."""
    stock = Stock(symbol, "SMART", "USD")
    await ib.qualifyContractsAsync(stock)
    [ticker] = await ib.reqTickersAsync(stock)
    return ticker.marketPrice()


async def get_option_chain_params(ib: IB, symbol: str) -> dict:
    """Get available expirations and strikes for symbol."""
    stock = Stock(symbol, "SMART", "USD")
    await ib.qualifyContractsAsync(stock)

    chains = await ib.reqSecDefOptParamsAsync(symbol, "", "STK", stock.conId)
    if not chains:
        return {"expirations": [], "strikes": []}

    # Prefer SMART exchange
    chain = next((c for c in chains if c.exchange == "SMART"), chains[0])
    return {
        "expirations": sorted(chain.expirations),
        "strikes": sorted(chain.strikes),
    }


async def get_option_quotes(ib: IB, symbol: str, expiry: str, strikes: list, right: str) -> list:
    """Get quotes for options at given strikes and expiry."""
    contracts = [Option(symbol, expiry, strike, right, "SMART") for strike in strikes]

    try:
        qualified = await asyncio.wait_for(ib.qualifyContractsAsync(*contracts), timeout=10)
    except asyncio.TimeoutError:
        return []

    # Filter out None values (contracts that don't exist)
    qualified = [c for c in qualified if c is not None]
    if not qualified:
        return []

    tickers = await asyncio.wait_for(ib.reqTickersAsync(*qualified), timeout=15)

    results = []
    for t in tickers:
        if t.contract is None:
            continue
        bid = t.bid if t.bid and t.bid > 0 else 0
        ask = t.ask if t.ask and t.ask > 0 else 0
        mid = (bid + ask) / 2 if bid and ask else 0

        results.append(
            {
                "strike": t.contract.strike,
                "expiry": t.contract.lastTradeDateOrContractMonth,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": t.last if t.last and t.last > 0 else 0,
            }
        )

    return sorted(results, key=lambda x: x["strike"])


def evaluate_short_candidates(
    quotes: list,
    underlying_price: float,
    right: str,
    days_to_exp: int,
) -> list:
    """Evaluate and score potential short options to open."""
    candidates = []
    for quote in quotes:
        if quote["bid"] <= 0:
            continue

        strike = quote["strike"]
        premium = quote["bid"]  # We sell at bid

        # Calculate OTM %
        if right == "C":
            otm_pct = ((strike - underlying_price) / underlying_price) * 100
        else:
            otm_pct = ((underlying_price - strike) / underlying_price) * 100

        # Skip ITM options
        if otm_pct < 0:
            continue

        # Annualized return on capital (for covered call: premium / strike)
        annual_factor = 365 / max(days_to_exp, 1)
        annual_return = (premium / underlying_price) * annual_factor * 100

        # Score based on:
        # - Premium (higher is better, but not at expense of safety)
        # - OTM% (prefer 3-10% OTM for safety)
        # - Days to expiry (prefer 30-60 days for theta decay)
        safety_score = min(otm_pct, 10) * 2  # Up to 20 points for OTM
        if otm_pct > 15:
            safety_score -= (otm_pct - 15) * 0.5  # Penalize too far OTM (low premium)

        premium_score = min(premium * 10, 30)  # Up to 30 points for premium

        time_score = 10 if 21 <= days_to_exp <= 60 else 5  # Prefer 21-60 DTE

        total_score = safety_score + premium_score + time_score

        candidates.append(
            {
                "strike": strike,
                "expiry": quote["expiry"],
                "bid": premium,
                "ask": quote["ask"],
                "otm_pct": otm_pct,
                "annual_return": annual_return,
                "days": days_to_exp,
                "score": total_score,
            }
        )

    return sorted(candidates, key=lambda x: x["score"], reverse=True)


def calculate_roll_options(current: dict, target_quotes: list, buy_price: float) -> list:
    """Calculate credit/debit for each roll option."""
    rolls = []
    for quote in target_quotes:
        if quote["bid"] <= 0:
            continue

        sell_price = quote["bid"]  # We sell at bid
        net = sell_price - buy_price  # Positive = credit

        rolls.append(
            {
                "strike": quote["strike"],
                "expiry": quote["expiry"],
                "sell_price": sell_price,
                "buy_price": buy_price,
                "net": net,
                "net_type": "credit" if net > 0 else "debit",
            }
        )

    return rolls


fetch_earnings_date = get_next_earnings_date


async def _find_roll(ib, symbol, current_position, chain_params):
    """Find roll candidates for an existing short position."""
    underlying_price = await get_underlying_price(ib, symbol)

    # Get current option quote for buy-to-close cost
    current_quotes = await get_option_quotes(
        ib,
        symbol,
        current_position["expiry"],
        [current_position["strike"]],
        current_position["right"],
    )

    if not current_quotes:
        return {"error": "Could not get quote for current position"}

    buy_price = current_quotes[0]["ask"]

    # Get future expirations after current
    current_exp = current_position["expiry"]
    future_exps = [e for e in chain_params["expirations"] if e > current_exp][:5]

    if not future_exps:
        return {"error": "No future expirations available"}

    # Determine strike range
    current_strike = current_position["strike"]
    all_strikes = chain_params["strikes"]

    if current_position["right"] == "C":
        target_strikes = [
            s for s in all_strikes
            if current_strike - 10 <= s <= current_strike + 50 and s % 5 == 0
        ]
    else:
        target_strikes = [
            s for s in all_strikes
            if current_strike - 50 <= s <= current_strike + 10 and s % 5 == 0
        ]

    target_strikes = sorted(target_strikes)[:10]

    # Fetch quotes for each target expiration
    roll_data = {}
    for exp in future_exps:
        quotes = await get_option_quotes(
            ib, symbol, exp, target_strikes, current_position["right"]
        )
        roll_data[exp] = calculate_roll_options(current_position, quotes, buy_price)

    earnings_date = fetch_earnings_date(symbol)

    return {
        "success": True,
        "mode": "roll",
        "symbol": symbol,
        "underlying_price": underlying_price,
        "current_position": {
            "strike": current_position["strike"],
            "expiry": current_position["expiry"],
            "right": current_position["right"],
            "quantity": current_position["quantity"],
        },
        "buy_to_close": buy_price,
        "roll_candidates": roll_data,
        "earnings_date": earnings_date,
        "expirations_analyzed": future_exps,
    }


async def _find_spread(ib, symbol, long_option, right, chain_params):
    """Find short candidates to create a vertical spread against a long option."""
    underlying_price = await get_underlying_price(ib, symbol)
    if math.isnan(underlying_price):
        underlying_price = long_option["strike"]
        print(
            f"{symbol} price unavailable, using long strike ${underlying_price:.2f}",
            file=sys.stderr,
        )

    long_expiry = long_option["expiry"]
    long_strike = long_option["strike"]

    # Check expirations at or after long option expiry
    target_exps = [e for e in chain_params["expirations"] if e >= long_expiry][:3]

    if not target_exps:
        return {"error": "No valid expirations available"}

    # Determine strike range (OTM relative to long strike)
    all_strikes = chain_params["strikes"]
    if right == "C":
        target_strikes = [s for s in all_strikes if long_strike < s <= underlying_price * 2.0]
    else:
        target_strikes = [s for s in all_strikes if underlying_price * 0.5 <= s < long_strike]

    target_strikes = sorted(target_strikes)[:15]

    # Fetch quotes and evaluate candidates
    candidates_by_expiry = {}
    for exp in target_exps:
        quotes = await get_option_quotes(ib, symbol, exp, target_strikes, right)
        dte = days_to_expiry(exp)
        candidates = evaluate_short_candidates(quotes, underlying_price, right, dte)
        if candidates:
            candidates_by_expiry[exp] = candidates

    earnings_date = fetch_earnings_date(symbol)

    return {
        "success": True,
        "mode": "spread",
        "symbol": symbol,
        "underlying_price": underlying_price,
        "right": right,
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


async def _find_new_short(ib, symbol, long_position, right, chain_params):
    """Find covered call/put candidates against a long stock position."""
    underlying_price = await get_underlying_price(ib, symbol)

    # Future expirations from today
    today_str = datetime.now().strftime("%Y%m%d")
    future_exps = [e for e in chain_params["expirations"] if e > today_str][:6]

    if not future_exps:
        return {"error": "No future expirations available"}

    # Determine OTM strike range
    all_strikes = chain_params["strikes"]
    if right == "C":
        target_strikes = [
            s for s in all_strikes if underlying_price <= s <= underlying_price * 1.20
        ]
    else:
        target_strikes = [
            s for s in all_strikes if underlying_price * 0.80 <= s <= underlying_price
        ]

    target_strikes = sorted(target_strikes)[:15]

    # Fetch quotes and evaluate candidates
    candidates_by_expiry = {}
    for exp in future_exps:
        quotes = await get_option_quotes(ib, symbol, exp, target_strikes, right)
        dte = days_to_expiry(exp)
        candidates = evaluate_short_candidates(quotes, underlying_price, right, dte)
        if candidates:
            candidates_by_expiry[exp] = candidates

    earnings_date = fetch_earnings_date(symbol)

    return {
        "success": True,
        "mode": "new_short",
        "symbol": symbol,
        "underlying_price": underlying_price,
        "right": right,
        "earnings_date": earnings_date,
        "long_position": {
            "shares": long_position["quantity"],
            "avg_cost": long_position["avg_cost"],
        },
        "candidates_by_expiry": candidates_by_expiry,
        "expirations_analyzed": future_exps,
    }


async def find_roll_candidates(
    symbol: str,
    port: int = 7496,
    account: str | None = None,
    strike: float | None = None,
    expiry: str | None = None,
    right: str = "C",
) -> dict:
    """Find roll, spread, or covered call/put candidates.

    Connects to IB and auto-detects the mode based on existing positions:
    - Short option found → roll mode (find roll candidates)
    - Long option found → spread mode (find short to create vertical spread)
    - Long stock found → new_short mode (find covered call/put candidates)
    """
    symbol = symbol.upper()
    ib = IB()
    try:
        await ib.connectAsync("127.0.0.1", port, clientId=30)
    except Exception as e:
        return {"error": f"Could not connect to IB on port {port}: {e}"}

    try:
        chain_params = await get_option_chain_params(ib, symbol)

        # Explicit strike/expiry → roll mode
        if strike and expiry:
            current_position = {
                "quantity": -1,
                "strike": strike,
                "expiry": expiry,
                "right": right,
                "account": account or "N/A",
            }
            return await _find_roll(ib, symbol, current_position, chain_params)

        # Auto-detect: try short position first
        current_position = await get_current_position(ib, symbol, account)
        if current_position:
            return await _find_roll(ib, symbol, current_position, chain_params)

        # No short → try long option for spread
        long_option = await get_long_option_position(ib, symbol, right, account)
        if long_option:
            return await _find_spread(ib, symbol, long_option, right, chain_params)

        # No long option → try long stock for covered call/put
        long_stock = await get_long_stock_position(ib, symbol, account)
        if long_stock:
            return await _find_new_short(ib, symbol, long_stock, right, chain_params)

        return {
            "error": f"No positions found for {symbol}. "
            "Use strike and expiry params to specify a short position manually."
        }

    finally:
        ib.disconnect()

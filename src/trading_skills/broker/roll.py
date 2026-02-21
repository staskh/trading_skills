# ABOUTME: Finds roll options for short positions using real-time IBKR data.
# ABOUTME: Generates markdown reports with credit/debit analysis and recommendations.

import asyncio
import sys
from datetime import datetime

from ib_async import IB, Option, Stock

from trading_skills.earnings import get_next_earnings_date
from trading_skills.utils import days_to_expiry, format_expiry_long


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


# format_expiry_long and days_to_expiry are imported from trading_skills.utils
format_expiry = format_expiry_long


fetch_earnings_date = get_next_earnings_date


def generate_report(
    symbol: str,
    underlying_price: float,
    current_position: dict,
    current_quote: dict,
    roll_data: dict,
    earnings_date: str = None,
) -> str:
    """Generate markdown roll analysis report."""
    now = datetime.now()
    date_str = now.strftime("%B %d, %Y at %H:%M")

    current_strike = current_position["strike"]
    current_expiry = current_position["expiry"]
    current_right = current_position["right"]
    quantity = abs(current_position["quantity"])
    buy_price = current_quote["ask"]  # Cost to close

    current_otm_pct = ((current_strike - underlying_price) / underlying_price) * 100
    if current_right == "P":
        current_otm_pct = ((underlying_price - current_strike) / underlying_price) * 100

    lines = [
        f"# Roll Analysis Report: {symbol}",
        f"**Generated:** {date_str}",
        "",
        "---",
        "",
        "## Current Short Position",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Symbol** | {symbol} |",
        f"| **Position** | -{quantity} "
        f"{'Call' if current_right == 'C' else 'Put'}"
        f"{'s' if quantity > 1 else ''} |",
        f"| **Strike** | ${current_strike:.2f} |",
        f"| **Expiration** | {format_expiry(current_expiry)} "
        f"({days_to_expiry(current_expiry)} days) |",
        f"| **Underlying Price** | ${underlying_price:.2f} |",
        f"| **OTM %** | {current_otm_pct:.1f}% |",
        f"| **Buy to Close** | ${buy_price:.2f} |",
        f"| **Total Cost to Close** | ${buy_price * quantity * 100:,.0f} |",
    ]

    if earnings_date:
        lines.append(f"| **Earnings Date** | {earnings_date} |")

    lines.extend(["", "---", ""])

    # Roll candidates by expiration
    lines.extend(
        [
            "## Roll Candidates",
            "",
        ]
    )

    best_rolls = []

    for expiry, rolls in sorted(roll_data.items()):
        if not rolls:
            continue

        exp_days = days_to_expiry(expiry)
        lines.extend(
            [
                f"### {format_expiry(expiry)} ({exp_days} days)",
                "",
                "| Strike | OTM% | Sell @ | Net | Total ({0} contracts) | Rating |".format(
                    quantity
                ),
                "|--------|------|--------|-----|----------------------|--------|",
            ]
        )

        for roll in rolls:
            strike = roll["strike"]
            otm_pct = ((strike - underlying_price) / underlying_price) * 100
            if current_right == "P":
                otm_pct = ((underlying_price - strike) / underlying_price) * 100

            net = roll["net"]
            net_str = f"+${net:.2f}" if net > 0 else f"-${abs(net):.2f}"
            net_type = "credit" if net > 0 else "debit"

            total = net * quantity * 100
            total_str = f"+${total:,.0f}" if total > 0 else f"-${abs(total):,.0f}"

            # Rating based on credit and OTM%
            if net > 0 and otm_pct >= 5:
                rating = "Excellent" if net > 2 else "Good"
            elif net > 0:
                rating = "OK"
            elif net > -1:
                rating = "Fair"
            else:
                rating = "Poor"

            lines.append(
                f"| ${strike:.1f} | {otm_pct:.1f}% | ${roll['sell_price']:.2f} | "
                f"**{net_str}** {net_type} | {total_str} | {rating} |"
            )

            # Track best rolls for recommendations
            if net > 0:
                best_rolls.append(
                    {
                        "expiry": expiry,
                        "expiry_str": format_expiry(expiry),
                        "strike": strike,
                        "otm_pct": otm_pct,
                        "net": net,
                        "total": total,
                        "days": exp_days,
                    }
                )

        lines.extend(["", ""])

    # Recommendations
    lines.extend(
        [
            "---",
            "",
            "## Recommendations",
            "",
        ]
    )

    if not best_rolls:
        lines.extend(
            [
                "No credit rolls available. Consider:",
                "- Accepting a debit to move strike higher",
                "- Waiting for better pricing",
                "- Closing position outright",
                "",
            ]
        )
    else:

        def roll_score(r):
            otm_improvement = r["otm_pct"] - current_otm_pct
            safety_score = r["otm_pct"] * 0.5 + max(0, otm_improvement) * 2
            credit_score = min(r["net"], 10) * 0.3
            time_score = min(r["days"] / 60, 3) * 0.2
            return safety_score + credit_score + time_score

        best_rolls.sort(key=roll_score, reverse=True)

        lines.extend(
            [
                "### Top Roll Candidates (Safety + Credit)",
                "",
            ]
        )

        for i, roll in enumerate(best_rolls[:5], 1):
            emoji = ["1.", "2.", "3.", "4.", "5."][i - 1]
            lines.extend(
                [
                    f"**{emoji} {roll['expiry_str']} ${roll['strike']:.1f}**",
                    f"   - Net credit: **+${roll['net']:.2f}** "
                    f"per contract (+${roll['total']:,.0f} total)",
                    f"   - Strike {roll['otm_pct']:.1f}% OTM",
                    f"   - {roll['days']} days to expiration",
                    "",
                ]
            )

        balanced = max(best_rolls, key=roll_score)

        lines.extend(
            [
                "---",
                "",
                "### Recommended Roll",
                "",
                f"**Roll to {balanced['expiry_str']} ${balanced['strike']:.1f}**",
                "",
                f"- Collect **+${balanced['net']:.2f}** credit per contract",
                f"- Total credit: **+${balanced['total']:,.0f}** for {quantity} contracts",
                f"- New strike {balanced['otm_pct']:.1f}% out of the money",
                f"- {balanced['days']} days to new expiration",
                "",
                "**Order:**",
                "```",
                f"BUY TO CLOSE  {quantity} {symbol} "
                f"{format_expiry(current_expiry)} "
                f"${current_strike:.1f} "
                f"{'CALL' if current_right == 'C' else 'PUT'} "
                f"@ ${buy_price:.2f}",
                f"SELL TO OPEN  {quantity} {symbol} "
                f"{balanced['expiry_str']} "
                f"${balanced['strike']:.1f} "
                f"{'CALL' if current_right == 'C' else 'PUT'} "
                f"@ ${balanced['net'] + buy_price:.2f}",
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            f"*Report generated by Trading Skills on {now.strftime('%Y-%m-%d %H:%M')}*",
        ]
    )

    return "\n".join(lines)


def generate_spread_short_report(
    symbol: str,
    underlying_price: float,
    long_option: dict,
    candidates_by_expiry: dict,
    right: str,
    earnings_date: str = None,
) -> str:
    """Generate markdown report for selling short call/put against long option (vertical spread)."""
    now = datetime.now()
    date_str = now.strftime("%B %d, %Y at %H:%M")

    quantity = long_option["quantity"]
    long_strike = long_option["strike"]
    long_expiry = long_option["expiry"]
    avg_cost = long_option["avg_cost"]

    option_type = "Call" if right == "C" else "Put"

    lines = [
        f"# Vertical Spread Analysis: {symbol}",
        f"**Generated:** {date_str}",
        "",
        "---",
        "",
        f"## Current Long {option_type} Position",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Symbol** | {symbol} |",
        f"| **Position** | +{quantity} {option_type}{'s' if quantity > 1 else ''} |",
        f"| **Strike** | ${long_strike:.2f} |",
        f"| **Expiration** | {format_expiry(long_expiry)} ({days_to_expiry(long_expiry)} days) |",
        f"| **Avg Cost** | ${avg_cost:.2f} |",
        f"| **Underlying Price** | ${underlying_price:.2f} |",
    ]

    if earnings_date:
        lines.append(f"| **Earnings Date** | {earnings_date} |")

    lines.extend(["", "---", ""])

    # Short candidates by expiration
    lines.extend(
        [
            f"## Short {option_type} Candidates (Create Vertical Spread)",
            "",
            f"Selling a higher strike {option_type.lower()} creates a "
            f"**{'bull' if right == 'C' else 'bear'} "
            f"{option_type.lower()} spread**.",
            "",
        ]
    )

    all_candidates = []

    for expiry, candidates in sorted(candidates_by_expiry.items()):
        if not candidates:
            continue

        exp_days = days_to_expiry(expiry)
        lines.extend(
            [
                f"### {format_expiry(expiry)} ({exp_days} days)",
                "",
                "| Strike | OTM% | Bid | Width | Max Profit | Max Loss | Score |",
                "|--------|------|-----|-------|------------|----------|-------|",
            ]
        )

        for c in candidates[:8]:  # Top 8 per expiry
            width = abs(c["strike"] - long_strike)
            premium = c["bid"]
            max_profit = premium * 100  # Premium received per contract
            net_debit = avg_cost - premium
            max_loss = max(net_debit, 0) * 100  # Net debit per contract

            lines.append(
                f"| ${c['strike']:.1f} | {c['otm_pct']:.1f}% | ${c['bid']:.2f} | "
                f"${width:.1f} | ${max_profit:.0f} | ${max_loss:.0f} | {c['score']:.0f} |"
            )
            c["width"] = width
            c["max_profit"] = max_profit
            c["max_loss"] = max_loss
            all_candidates.append(c)

        lines.extend(["", ""])

    # Recommendations
    lines.extend(
        [
            "---",
            "",
            "## Recommendations",
            "",
        ]
    )

    if not all_candidates:
        lines.extend(
            [
                "No suitable short options found. Consider:",
                "- Waiting for higher implied volatility",
                "- Looking at different expirations",
                "",
            ]
        )
    else:
        all_candidates.sort(key=lambda x: x["score"], reverse=True)

        lines.extend(
            [
                "### Top Candidates (Ranked by Score)",
                "",
            ]
        )

        for i, c in enumerate(all_candidates[:5], 1):
            total_premium = c["bid"] * quantity * 100
            lines.extend(
                [
                    f"**{i}. {format_expiry(c['expiry'])} ${c['strike']:.1f} {option_type}**",
                    f"   - Premium: **${c['bid']:.2f}** per share "
                    f"(${c['bid'] * 100:.0f} per contract)",
                    f"   - Total for {quantity} contracts: "
                    f"**${total_premium:,.0f}**",
                    f"   - Strike {c['otm_pct']:.1f}% out of the money",
                    f"   - Spread width: ${c['width']:.1f}",
                    f"   - {c['days']} days to expiration",
                    "",
                ]
            )

        best = all_candidates[0]
        best_premium = best["bid"] * quantity * 100
        spread_width = abs(best["strike"] - long_strike)
        best_exp = format_expiry(best['expiry'])
        spread_type = "debit" if avg_cost > best["bid"] else "credit"
        net_cost = abs(avg_cost - best["bid"])

        lines.extend(
            [
                "---",
                "",
                "### Recommended Position",
                "",
                f"**SELL {quantity} {symbol} {best_exp} "
                f"${best['strike']:.1f} {option_type.upper()}**",
                "",
                f"This creates a **{option_type.lower()} "
                f"{spread_type} spread**:",
                f"- Long ${long_strike:.1f} "
                f"{option_type.lower()} @ ${avg_cost:.2f}",
                f"- Short ${best['strike']:.1f} "
                f"{option_type.lower()} @ ${best['bid']:.2f}",
                f"- Spread width: **${spread_width:.1f}**",
                f"- Net {spread_type}: "
                f"**${net_cost:.2f}** per share",
                f"- Premium collected: **${best_premium:,.0f}** total",
                "",
                "**Order:**",
                "```",
                f"SELL TO OPEN  {quantity} {symbol} "
                f"{best_exp} ${best['strike']:.1f} "
                f"{option_type.upper()} @ ${best['bid']:.2f}",
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            f"*Report generated by Trading Skills on {now.strftime('%Y-%m-%d %H:%M')}*",
        ]
    )

    return "\n".join(lines)


def generate_new_short_report(
    symbol: str,
    underlying_price: float,
    long_position: dict,
    candidates_by_expiry: dict,
    right: str,
    earnings_date: str = None,
) -> str:
    """Generate markdown report for opening a new short position."""
    now = datetime.now()
    date_str = now.strftime("%B %d, %Y at %H:%M")

    quantity = long_position["quantity"]
    contracts = quantity // 100  # Number of covered calls possible
    avg_cost = long_position["avg_cost"]

    lines = [
        f"# New Short Position Analysis: {symbol}",
        f"**Generated:** {date_str}",
        "",
        "---",
        "",
        "## Current Long Stock Position",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Symbol** | {symbol} |",
        f"| **Shares** | {quantity:,} |",
        f"| **Avg Cost** | ${avg_cost:.2f} |",
        f"| **Current Price** | ${underlying_price:.2f} |",
        f"| **P&L** | "
        f"${(underlying_price - avg_cost) * quantity:,.2f} "
        f"({((underlying_price - avg_cost) / avg_cost * 100):.1f}%) |",
        f"| **Contracts Available** | {contracts} (100 shares each) |",
    ]

    if earnings_date:
        lines.append(f"| **Earnings Date** | {earnings_date} |")

    lines.extend(["", "---", ""])

    # Short candidates by expiration
    lines.extend(
        [
            f"## {'Covered Call' if right == 'C' else 'Protective Put'} Candidates",
            "",
        ]
    )

    all_candidates = []

    for expiry, candidates in sorted(candidates_by_expiry.items()):
        if not candidates:
            continue

        exp_days = days_to_expiry(expiry)
        lines.extend(
            [
                f"### {format_expiry(expiry)} ({exp_days} days)",
                "",
                "| Strike | OTM% | Bid | Premium/Contract | Ann. Return | Score |",
                "|--------|------|-----|------------------|-------------|-------|",
            ]
        )

        for c in candidates[:8]:  # Top 8 per expiry
            total_premium = c["bid"] * contracts * 100
            lines.append(
                f"| ${c['strike']:.1f} | {c['otm_pct']:.1f}% | ${c['bid']:.2f} | "
                f"${c['bid'] * 100:.0f} | {c['annual_return']:.1f}% | {c['score']:.0f} |"
            )
            all_candidates.append(c)

        lines.extend(["", ""])

    # Recommendations
    lines.extend(
        [
            "---",
            "",
            "## Recommendations",
            "",
        ]
    )

    if not all_candidates:
        lines.extend(
            [
                "No suitable short options found. Consider:",
                "- Waiting for higher implied volatility",
                "- Looking at different expirations",
                "",
            ]
        )
    else:
        all_candidates.sort(key=lambda x: x["score"], reverse=True)

        lines.extend(
            [
                "### Top Candidates (Ranked by Score)",
                "",
            ]
        )

        for i, c in enumerate(all_candidates[:5], 1):
            total_premium = c["bid"] * contracts * 100
            lines.extend(
                [
                    f"**{i}. {format_expiry(c['expiry'])} "
                    f"${c['strike']:.1f} "
                    f"{'Call' if right == 'C' else 'Put'}**",
                    f"   - Premium: **${c['bid']:.2f}** per share "
                    f"(${c['bid'] * 100:.0f} per contract)",
                    f"   - Total for {contracts} contracts: **${total_premium:,.0f}**",
                    f"   - Strike {c['otm_pct']:.1f}% out of the money",
                    f"   - Annualized return: {c['annual_return']:.1f}%",
                    f"   - {c['days']} days to expiration",
                    "",
                ]
            )

        best = all_candidates[0]
        best_premium = best["bid"] * contracts * 100

        lines.extend(
            [
                "---",
                "",
                "### Recommended Position",
                "",
                f"**SELL {contracts} {symbol} "
                f"{format_expiry(best['expiry'])} "
                f"${best['strike']:.1f} "
                f"{'CALL' if right == 'C' else 'PUT'}**",
                "",
                f"- Collect **${best['bid']:.2f}** per share",
                f"- Total premium: **${best_premium:,.0f}**",
                f"- Strike {best['otm_pct']:.1f}% above current price"
                if right == "C"
                else f"- Strike {best['otm_pct']:.1f}% below current price",
                (
                    f"- Max profit if called away: "
                    f"${(best['strike'] - avg_cost) * quantity + best_premium:,.0f}"
                    if right == "C"
                    else ""
                ),
                f"- {best['days']} days to expiration",
                "",
                "**Order:**",
                "```",
                f"SELL TO OPEN  {contracts} {symbol} "
                f"{format_expiry(best['expiry'])} "
                f"${best['strike']:.1f} "
                f"{'CALL' if right == 'C' else 'PUT'} "
                f"@ ${best['bid']:.2f}",
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            f"*Report generated by Trading Skills on {now.strftime('%Y-%m-%d %H:%M')}*",
        ]
    )

    return "\n".join(lines)

# ABOUTME: Calculates delta-adjusted notional exposure for IBKR portfolio.
# ABOUTME: Uses Black-Scholes for option deltas, reports by account and underlying.

import asyncio
from datetime import date, datetime

from ib_async import IB, Stock

from trading_skills.black_scholes import black_scholes_delta, estimate_iv
from trading_skills.utils import fetch_with_timeout


async def get_delta_exposure(port: int = 7497):
    """Fetch portfolio and calculate delta-adjusted notional."""
    ib = IB()

    try:
        await ib.connectAsync(host="127.0.0.1", port=port, clientId=10)
    except Exception as e:
        return {
            "connected": False,
            "error": f"Could not connect to IB on port {port}. Is TWS/Gateway running? Error: {e}",
        }

    managed = ib.managedAccounts()

    try:
        await asyncio.sleep(2)

        all_positions = []
        for acct in managed:
            positions = ib.positions(account=acct)
            all_positions.extend(positions)

        # Separate by type
        option_positions = [p for p in all_positions if p.contract.secType == "OPT"]
        fut_opt_positions = [p for p in all_positions if p.contract.secType == "FOP"]
        future_positions = [p for p in all_positions if p.contract.secType == "FUT"]
        stock_positions = [p for p in all_positions if p.contract.secType == "STK"]

        # Get underlying prices for equity options
        underlying_symbols = {p.contract.symbol for p in option_positions}
        spot_prices = {}

        if underlying_symbols:
            stock_contracts = []
            for sym in underlying_symbols:
                try:
                    stock_contracts.append(Stock(sym, "SMART", "USD"))
                except Exception:
                    pass

            if stock_contracts:
                qualified = await fetch_with_timeout(
                    ib.qualifyContractsAsync(*stock_contracts), timeout=30.0, default=[]
                )
                if qualified:
                    for i in range(0, len(qualified), 20):
                        batch = qualified[i : i + 20]
                        tickers = await fetch_with_timeout(
                            ib.reqTickersAsync(*batch), timeout=30.0, default=[]
                        )
                        for ticker in tickers or []:
                            price = ticker.marketPrice()
                            if price and price > 0:
                                spot_prices[ticker.contract.symbol] = price
                        await asyncio.sleep(0.5)

        today = date.today()
        results = []

        # Process equity options
        for pos in option_positions:
            c = pos.contract
            symbol = c.symbol
            spot = spot_prices.get(symbol)
            if not spot:
                spot = c.strike * 0.95  # Fallback estimate

            strike = c.strike
            expiry_str = c.lastTradeDateOrContractMonth
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d").date()
            dte = (expiry_date - today).days
            dte_years = max(dte / 365.0, 0.001)

            is_call = c.right == "C"
            multiplier = int(c.multiplier) if c.multiplier else 100
            qty = pos.position

            option_type = "call" if is_call else "put"
            iv = estimate_iv(spot, strike, dte_years, option_type)
            delta = black_scholes_delta(spot, strike, dte_years, 0.05, iv, option_type)

            delta_notional = delta * spot * qty * multiplier
            raw_notional = spot * qty * multiplier

            results.append(
                {
                    "account": pos.account,
                    "symbol": symbol,
                    "sec_type": "OPT",
                    "strike": strike,
                    "expiry": expiry_str,
                    "right": c.right,
                    "qty": qty,
                    "spot": round(spot, 2),
                    "delta": round(delta, 4),
                    "multiplier": multiplier,
                    "raw_notional": round(raw_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Process futures options (FOP)
        for pos in fut_opt_positions:
            c = pos.contract
            symbol = c.symbol
            strike = c.strike
            expiry_str = c.lastTradeDateOrContractMonth
            expiry_date = datetime.strptime(expiry_str, "%Y%m%d").date()
            dte = (expiry_date - today).days
            dte_years = max(dte / 365.0, 0.001)

            is_call = c.right == "C"
            multiplier = int(c.multiplier) if c.multiplier else 20
            qty = pos.position

            # Estimate futures spot from symbol
            spot = 21500 if symbol == "NQ" else 5000 if symbol == "ES" else strike

            iv = 0.20  # Lower IV for index futures
            option_type = "call" if is_call else "put"
            delta = black_scholes_delta(spot, strike, dte_years, 0.05, iv, option_type)

            delta_notional = delta * spot * qty * multiplier
            raw_notional = spot * qty * multiplier

            results.append(
                {
                    "account": pos.account,
                    "symbol": symbol,
                    "sec_type": "FOP",
                    "strike": strike,
                    "expiry": expiry_str,
                    "right": c.right,
                    "qty": qty,
                    "spot": spot,
                    "delta": round(delta, 4),
                    "multiplier": multiplier,
                    "raw_notional": round(raw_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Process futures (delta = 1)
        for pos in future_positions:
            c = pos.contract
            multiplier = int(c.multiplier) if c.multiplier else 20
            qty = pos.position
            avg_cost = pos.avgCost
            spot = avg_cost / multiplier if multiplier else avg_cost

            delta_notional = spot * qty * multiplier

            results.append(
                {
                    "account": pos.account,
                    "symbol": c.symbol,
                    "sec_type": "FUT",
                    "qty": qty,
                    "spot": round(spot, 2),
                    "delta": 1.0,
                    "multiplier": multiplier,
                    "raw_notional": round(delta_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Process stocks (delta = 1)
        for pos in stock_positions:
            c = pos.contract
            spot = spot_prices.get(c.symbol, pos.avgCost)
            qty = pos.position

            delta_notional = spot * qty

            results.append(
                {
                    "account": pos.account,
                    "symbol": c.symbol,
                    "sec_type": "STK",
                    "qty": qty,
                    "spot": round(spot, 2),
                    "delta": 1.0,
                    "multiplier": 1,
                    "raw_notional": round(delta_notional, 2),
                    "delta_notional": round(delta_notional, 2),
                }
            )

        # Calculate summaries
        long_delta_notional = sum(p["delta_notional"] for p in results if p["delta_notional"] > 0)
        short_delta_notional = sum(p["delta_notional"] for p in results if p["delta_notional"] < 0)

        # By account
        account_summary = {}
        for p in results:
            acct = p["account"]
            if acct not in account_summary:
                account_summary[acct] = {"long": 0, "short": 0}
            if p["delta_notional"] > 0:
                account_summary[acct]["long"] += p["delta_notional"]
            else:
                account_summary[acct]["short"] += p["delta_notional"]

        # By underlying
        underlying_summary = {}
        for p in results:
            sym = p["symbol"]
            if sym not in underlying_summary:
                underlying_summary[sym] = {"long": 0, "short": 0}
            if p["delta_notional"] > 0:
                underlying_summary[sym]["long"] += p["delta_notional"]
            else:
                underlying_summary[sym]["short"] += p["delta_notional"]

        return {
            "connected": True,
            "accounts": managed,
            "position_count": len(results),
            "positions": results,
            "summary": {
                "total_long_delta_notional": round(long_delta_notional, 2),
                "total_short_delta_notional": round(short_delta_notional, 2),
                "net_delta_notional": round(long_delta_notional + short_delta_notional, 2),
                "by_account": {
                    k: {"long": round(v["long"], 2), "short": round(v["short"], 2)}
                    for k, v in account_summary.items()
                },
                "by_underlying": {
                    k: {
                        "long": round(v["long"], 2),
                        "short": round(v["short"], 2),
                        "net": round(v["long"] + v["short"], 2),
                    }
                    for k, v in underlying_summary.items()
                },
            },
        }

    finally:
        ib.disconnect()


def format_markdown(data, full_report=False):
    """Format the result as markdown."""
    if not data.get("connected"):
        return f"Error: {data.get('error', 'Unknown error')}"

    summary = data["summary"]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Delta-Adjusted Notional Exposure Report",
        "",
        f"**Generated:** {timestamp}",
        f"**Accounts:** {', '.join(data['accounts'])}",
        f"**Positions:** {data['position_count']}",
        "",
        "---",
        "",
        "## Portfolio Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Total Long** | **${summary['total_long_delta_notional']:,.0f}** |",
        f"| **Total Short** | **${summary['total_short_delta_notional']:,.0f}** |",
        f"| **Net Exposure** | **${summary['net_delta_notional']:,.0f}** |",
        "",
        "---",
        "",
        "## Summary by Account",
        "",
        "| Account | Long | Short | Net |",
        "|---------|-----:|------:|----:|",
    ]

    for acct, vals in summary["by_account"].items():
        net = vals["long"] + vals["short"]
        lines.append(f"| {acct} | ${vals['long']:,.0f} | ${vals['short']:,.0f} | ${net:,.0f} |")

    # Summary by underlying
    lines.extend(
        [
            "",
            "---",
            "",
            "## Summary by Underlying",
            "",
            "| Symbol | Long | Short | Net |",
            "|--------|-----:|------:|----:|",
        ]
    )

    sorted_underlying = sorted(
        summary["by_underlying"].items(), key=lambda x: abs(x[1]["net"]), reverse=True
    )
    for sym, vals in sorted_underlying:
        if vals["long"] != 0 or vals["short"] != 0:
            lines.append(
                f"| {sym} | ${vals['long']:,.0f} | ${vals['short']:,.0f} | ${vals['net']:,.0f} |"
            )

    positions = data["positions"]

    if full_report:
        lines.extend(
            [
                "",
                "---",
                "",
                "## Detailed Positions by Account",
            ]
        )

        accounts = {}
        for p in positions:
            acct = p["account"]
            if acct not in accounts:
                accounts[acct] = []
            accounts[acct].append(p)

        for acct in sorted(accounts.keys()):
            acct_positions = accounts[acct]
            acct_long = sum(p["delta_notional"] for p in acct_positions if p["delta_notional"] > 0)
            acct_short = sum(p["delta_notional"] for p in acct_positions if p["delta_notional"] < 0)

            lines.extend(
                [
                    "",
                    f"### Account: {acct}",
                    "",
                    f"**Long:** ${acct_long:,.0f} | "
                    f"**Short:** ${acct_short:,.0f} | "
                    f"**Net:** ${acct_long + acct_short:,.0f}",
                    "",
                ]
            )

            long_pos = sorted(
                [p for p in acct_positions if p["delta_notional"] > 0],
                key=lambda x: x["delta_notional"],
                reverse=True,
            )
            if long_pos:
                lines.extend(
                    [
                        "#### Long Positions",
                        "",
                        "| Symbol | Type | Strike | Expiry | Qty | Spot | Delta | Delta Notional |",
                        "|--------|------|--------|--------|----:|-----:|------:|---------------:|",
                    ]
                )
                for p in long_pos:
                    strike = p.get("strike", "-")
                    expiry = p.get("expiry", "-")
                    if expiry != "-":
                        expiry = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
                    right = p.get("right", "")
                    type_str = f"{p['sec_type']}" + (f" {right}" if right else "")
                    sym = p["symbol"]
                    qty = f"{p['qty']:.0f}"
                    spot = f"${p['spot']:,.2f}"
                    delta = f"{p['delta']:.4f}"
                    dn = f"${p['delta_notional']:,.0f}"
                    lines.append(
                        f"| {sym} | {type_str} | {strike} "
                        f"| {expiry} | {qty} | {spot} "
                        f"| {delta} | {dn} |"
                    )
                lines.append("")

            short_pos = sorted(
                [p for p in acct_positions if p["delta_notional"] < 0],
                key=lambda x: x["delta_notional"],
            )
            if short_pos:
                lines.extend(
                    [
                        "#### Short Positions",
                        "",
                        "| Symbol | Type | Strike | Expiry | Qty | Spot | Delta | Delta Notional |",
                        "|--------|------|--------|--------|----:|-----:|------:|---------------:|",
                    ]
                )
                for p in short_pos:
                    strike = p.get("strike", "-")
                    expiry = p.get("expiry", "-")
                    if expiry != "-":
                        expiry = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
                    right = p.get("right", "")
                    type_str = f"{p['sec_type']}" + (f" {right}" if right else "")
                    sym = p["symbol"]
                    qty = f"{p['qty']:.0f}"
                    spot = f"${p['spot']:,.2f}"
                    delta = f"{p['delta']:.4f}"
                    dn = f"${p['delta_notional']:,.0f}"
                    lines.append(
                        f"| {sym} | {type_str} | {strike} "
                        f"| {expiry} | {qty} | {spot} "
                        f"| {delta} | {dn} |"
                    )
                lines.append("")

        lines.extend(
            [
                "",
                "---",
                "",
                "## Detailed Positions by Symbol",
            ]
        )

        symbols = {}
        for p in positions:
            sym = p["symbol"]
            if sym not in symbols:
                symbols[sym] = []
            symbols[sym].append(p)

        for sym in sorted(symbols.keys()):
            sym_positions = symbols[sym]
            sym_long = sum(p["delta_notional"] for p in sym_positions if p["delta_notional"] > 0)
            sym_short = sum(p["delta_notional"] for p in sym_positions if p["delta_notional"] < 0)

            lines.extend(
                [
                    "",
                    f"### {sym}",
                    "",
                    f"**Long:** ${sym_long:,.0f} | "
                    f"**Short:** ${sym_short:,.0f} | "
                    f"**Net:** ${sym_long + sym_short:,.0f}",
                    "",
                    "| Account | Type | Strike | Expiry | Qty | Spot | Delta | Delta Notional |",
                    "|---------|------|--------|--------|----:|-----:|------:|---------------:|",
                ]
            )

            sorted_pos = sorted(sym_positions, key=lambda x: x["delta_notional"], reverse=True)
            for p in sorted_pos:
                strike = p.get("strike", "-")
                expiry = p.get("expiry", "-")
                if expiry != "-":
                    expiry = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
                right = p.get("right", "")
                type_str = f"{p['sec_type']}" + (f" {right}" if right else "")
                acct = p["account"]
                qty = f"{p['qty']:.0f}"
                spot = f"${p['spot']:,.2f}"
                delta = f"{p['delta']:.4f}"
                dn = f"${p['delta_notional']:,.0f}"
                lines.append(
                    f"| {acct} | {type_str} | {strike} "
                    f"| {expiry} | {qty} | {spot} "
                    f"| {delta} | {dn} |"
                )

    else:
        long_positions = sorted(
            [p for p in positions if p["delta_notional"] > 0],
            key=lambda x: x["delta_notional"],
            reverse=True,
        )[:10]
        short_positions = sorted(
            [p for p in positions if p["delta_notional"] < 0], key=lambda x: x["delta_notional"]
        )[:10]

        lines.extend(
            [
                "",
                "---",
                "",
                "## Top Long Delta Exposures",
                "",
                "| Symbol | Type | Strike | Expiry | Qty | Delta | Delta Notional |",
                "|--------|------|--------|--------|----:|------:|---------------:|",
            ]
        )

        for p in long_positions:
            strike = p.get("strike", "-")
            expiry = p.get("expiry", "-")
            if expiry != "-":
                expiry = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
            right = p.get("right", "")
            type_str = f"{p['sec_type']}" + (f" {right}" if right else "")
            sym = p["symbol"]
            qty = f"{p['qty']:.0f}"
            delta = f"{p['delta']:.2f}"
            dn = f"${p['delta_notional']:,.0f}"
            lines.append(
                f"| {sym} | {type_str} | {strike} "
                f"| {expiry} | {qty} | {delta} | {dn} |"
            )

        lines.extend(
            [
                "",
                "## Top Short Delta Exposures",
                "",
                "| Symbol | Type | Strike | Expiry | Qty | Delta | Delta Notional |",
                "|--------|------|--------|--------|----:|------:|---------------:|",
            ]
        )

        for p in short_positions:
            strike = p.get("strike", "-")
            expiry = p.get("expiry", "-")
            if expiry != "-":
                expiry = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:]}"
            right = p.get("right", "")
            type_str = f"{p['sec_type']}" + (f" {right}" if right else "")
            sym = p["symbol"]
            qty = f"{p['qty']:.0f}"
            delta = f"{p['delta']:.2f}"
            dn = f"${p['delta_notional']:,.0f}"
            lines.append(
                f"| {sym} | {type_str} | {strike} "
                f"| {expiry} | {qty} | {delta} | {dn} |"
            )

    return "\n".join(lines)

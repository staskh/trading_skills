# ABOUTME: Consolidates IBRK trade CSV files into summary reports.
# ABOUTME: Groups trades by symbol, underlying, date, strike, buy/sell, and open/close.

import asyncio
import csv
from datetime import datetime
from pathlib import Path

from trading_skills.utils import format_expiry_iso

# Key columns for grouping
GROUP_COLS = [
    "UnderlyingSymbol",
    "Symbol",
    "TradeDate",
    "Strike",
    "Put/Call",
    "Buy/Sell",
    "Open/CloseIndicator",
]

# Columns to aggregate (sum)
AGG_COLS = [
    "Quantity",
    "Proceeds",
    "NetCash",
    "IBCommission",
    "FifoPnlRealized",
]

# Additional columns to keep (first value in group)
KEEP_COLS = [
    "ClientAccountID",
    "Description",
    "Expiry",
]


def determine_position(buy_sell: str, open_close: str) -> str:
    """Determine position type based on buy/sell and open/close indicators."""
    buy_sell = buy_sell.upper().strip()
    open_close = open_close.upper().strip()

    if open_close == "O":  # Opening
        return "SHORT" if buy_sell == "SELL" else "LONG"
    else:  # Closing
        return "CLOSE_SHORT" if buy_sell == "BUY" else "CLOSE_LONG"


def read_csv_files(directory: Path) -> tuple[list[dict], list[Path]]:
    """Read all CSV files in directory (not subdirectories).

    Returns tuple of (rows, processed_files).
    """
    all_rows = []
    processed_files = []
    csv_files = list(directory.glob("*.csv"))

    if not csv_files:
        print(f"No CSV files found in {directory}")
        return all_rows, processed_files

    print(f"Found {len(csv_files)} CSV files in {directory}")

    for csv_file in csv_files:
        try:
            with open(csv_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

                # Validate required columns exist
                if rows:
                    missing = [c for c in GROUP_COLS + AGG_COLS if c not in rows[0]]
                    if missing:
                        print(f"  Skipping {csv_file.name}: missing columns {missing}")
                        continue

                all_rows.extend(rows)
                processed_files.append(csv_file)
                print(f"  Read {len(rows)} rows from {csv_file.name}")
        except Exception as e:
            print(f"  Error reading {csv_file.name}: {e}")

    return all_rows, processed_files


def consolidate_rows(rows: list[dict]) -> list[dict]:
    """Consolidate rows by grouping columns and aggregating values."""
    groups = {}

    for row in rows:
        # Build group key
        key_parts = []
        for col in GROUP_COLS:
            val = row.get(col, "").strip()
            key_parts.append(val)
        key = tuple(key_parts)

        if key not in groups:
            # Initialize group with first row data
            groups[key] = {col: row.get(col, "").strip() for col in GROUP_COLS}
            for col in KEEP_COLS:
                groups[key][col] = row.get(col, "").strip()
            for col in AGG_COLS:
                groups[key][col] = 0.0

        # Aggregate numeric columns
        for col in AGG_COLS:
            try:
                val = float(row.get(col, 0) or 0)
                groups[key][col] += val
            except (ValueError, TypeError):
                pass

    # Convert to list and add Position column
    result = []
    for data in groups.values():
        data["Position"] = determine_position(
            data.get("Buy/Sell", ""), data.get("Open/CloseIndicator", "")
        )
        result.append(data)

    # Sort by underlying, date, symbol
    result.sort(
        key=lambda x: (
            x.get("UnderlyingSymbol", ""),
            x.get("TradeDate", ""),
            x.get("Symbol", ""),
        )
    )

    return result


async def fetch_unrealized_pnl(port: int = None) -> tuple[dict[str, float], str | None]:
    """Fetch unrealized P&L by underlying symbol from IB portfolio.

    If port is None, tries both 7496 (live) and 7497 (paper) ports.

    Returns tuple of (unrealized_pnl_by_symbol, account_id).
    """
    try:
        from ib_async import IB, Stock
    except ImportError:
        print("Warning: ib_async not available, skipping unrealized P&L")
        return {}, None

    ib = IB()
    unrealized_by_symbol = {}
    account_id = None

    # Determine ports to try
    if port:
        ports_to_try = [port]
    else:
        ports_to_try = [7496, 7497]  # Try live first, then paper

    connected_port = None
    for try_port in ports_to_try:
        try:
            print(f"Trying to connect to IB on port {try_port}...")
            await ib.connectAsync(host="127.0.0.1", port=try_port, clientId=99)
            connected_port = try_port
            print(f"Connected to IB on port {try_port}")
            break
        except Exception as e:
            print(f"  Port {try_port} not available: {e}")
            continue

    if not connected_port:
        print("Warning: Could not connect to IB on any port")
        return {}, None

    try:
        # Wait for position data to sync
        await asyncio.sleep(2)

        # Get account ID
        managed_accounts = ib.managedAccounts()
        if managed_accounts:
            account_id = managed_accounts[0]
            print(f"Account: {account_id}")

        # Get all positions
        all_positions = ib.positions()
        print(f"Found {len(all_positions)} positions in portfolio")

        # Separate options from other positions
        option_positions = [p for p in all_positions if p.contract.secType == "OPT"]

        # Get unique underlying symbols
        underlying_symbols = {p.contract.symbol for p in option_positions}

        # Fetch spot prices for underlyings
        spot_prices = {}
        if underlying_symbols:
            stock_contracts = [Stock(sym, "SMART", "USD") for sym in underlying_symbols]
            try:
                qualified = await asyncio.wait_for(
                    ib.qualifyContractsAsync(*stock_contracts), timeout=15.0
                )
                if qualified:
                    tickers = await asyncio.wait_for(ib.reqTickersAsync(*qualified), timeout=15.0)
                    for ticker in tickers or []:
                        price = ticker.marketPrice()
                        if price and price > 0:
                            spot_prices[ticker.contract.symbol] = price
            except asyncio.TimeoutError:
                print("Warning: Timeout fetching spot prices")

        # Fetch option prices
        option_prices = {}
        if option_positions:
            option_contracts = [p.contract for p in option_positions]
            try:
                qualified_opts = await asyncio.wait_for(
                    ib.qualifyContractsAsync(*option_contracts), timeout=15.0
                )
                if qualified_opts:
                    opt_tickers = await asyncio.wait_for(
                        ib.reqTickersAsync(*qualified_opts), timeout=15.0
                    )
                    for ticker in opt_tickers or []:
                        c = ticker.contract
                        key = (c.symbol, c.strike, c.lastTradeDateOrContractMonth, c.right)
                        price = ticker.marketPrice()
                        if price and price > 0:
                            option_prices[key] = price
            except asyncio.TimeoutError:
                print("Warning: Timeout fetching option prices")

        # Calculate unrealized P&L by underlying
        for pos in option_positions:
            contract = pos.contract
            symbol = contract.symbol
            multiplier = int(contract.multiplier) if contract.multiplier else 100
            key = (
                contract.symbol,
                contract.strike,
                contract.lastTradeDateOrContractMonth,
                contract.right,
            )
            market_price = option_prices.get(key)

            if market_price:
                unrealized = (market_price - pos.avgCost / multiplier) * pos.position * multiplier
                unrealized_by_symbol[symbol] = unrealized_by_symbol.get(symbol, 0) + unrealized

        # Round values
        unrealized_by_symbol = {k: round(v, 2) for k, v in unrealized_by_symbol.items()}
        print(f"Calculated unrealized P&L for {len(unrealized_by_symbol)} symbols")

    finally:
        ib.disconnect()

    return unrealized_by_symbol, account_id


# format_expiry_iso is imported from trading_skills.utils
format_date = format_expiry_iso


def format_money(value: float, bold: bool = False) -> str:
    """Format money value, with red color for negative numbers."""
    formatted = f"${value:,.2f}"
    if bold:
        formatted = f"**{formatted}**"
    if value < 0:
        return f'<span style="color:red">{formatted}</span>'
    return formatted


def generate_markdown(
    consolidated: list[dict],
    unrealized_pnl: dict[str, float],
    processed_files: list[Path],
    output_path: Path,
):
    """Generate markdown report."""
    has_unrealized = bool(unrealized_pnl)

    lines = [
        "# Consolidated Trades Report",
        f"**Generated:** {datetime.now().strftime('%B %d, %Y at %H:%M')}",
        "",
        f"**Total Consolidated Rows:** {len(consolidated)}",
    ]

    if has_unrealized:
        lines.append("**Portfolio Data:** Connected to IB")
    else:
        lines.append("**Portfolio Data:** Not available (no IB connection)")

    lines.append("")
    lines.append(f"**Processed Files ({len(processed_files)}):**")
    for f in processed_files:
        lines.append(f"- `{f}`")

    lines.extend(["", "---", ""])

    # Group by underlying for summary
    by_underlying = {}
    for row in consolidated:
        underlying = row.get("UnderlyingSymbol", "UNKNOWN")
        if underlying not in by_underlying:
            by_underlying[underlying] = []
        by_underlying[underlying].append(row)

    # Summary table
    summary_data = []
    for underlying in by_underlying.keys():
        rows = by_underlying[underlying]
        net_cash = sum(r.get("NetCash", 0) for r in rows)
        pnl = sum(r.get("FifoPnlRealized", 0) for r in rows)
        commission = sum(r.get("IBCommission", 0) for r in rows)
        total_realized = pnl + commission
        unrealized = unrealized_pnl.get(underlying, 0)
        total_pnl = total_realized + unrealized

        total_qty = sum(r.get("Quantity", 0) for r in rows)

        long_pnl = sum(
            r.get("FifoPnlRealized", 0) for r in rows if r.get("Position") == "CLOSE_LONG"
        )
        short_pnl = sum(
            r.get("FifoPnlRealized", 0) for r in rows if r.get("Position") == "CLOSE_SHORT"
        )

        summary_data.append(
            {
                "underlying": underlying,
                "trades": len(rows),
                "total_qty": total_qty,
                "net_cash": net_cash,
                "pnl": pnl,
                "long_pnl": long_pnl,
                "short_pnl": short_pnl,
                "commission": commission,
                "total_realized": total_realized,
                "unrealized": unrealized,
                "total_pnl": total_pnl,
            }
        )

    summary_data.sort(key=lambda x: x["total_pnl"], reverse=True)

    lines.append("## Summary by Underlying")
    lines.append("")

    hdr_base = (
        "| Underlying | Trades | Total Qty"
        " | Realized P&L Long | Realized P&L Short"
        " | Commission | Total Realized P&L"
    )
    sep_base = (
        "|------------|--------|-----------|"
        "-------------------|-------------------|"
        "------------|-------------------"
    )
    if has_unrealized:
        lines.append(hdr_base + " | Unrealized P&L | Total P&L |")
        lines.append(sep_base + "|----------------|-----------|")
    else:
        lines.append(hdr_base + " |")
        lines.append(sep_base + "|")

    grand_total_pnl = 0
    grand_total_long_pnl = 0
    grand_total_short_pnl = 0
    grand_total_commission = 0
    grand_total_unrealized = 0
    grand_total_qty = 0

    for row in summary_data:
        grand_total_pnl += row["pnl"]
        grand_total_long_pnl += row["long_pnl"]
        grand_total_short_pnl += row["short_pnl"]
        grand_total_commission += row["commission"]
        grand_total_unrealized += row["unrealized"]
        grand_total_qty += row["total_qty"]

        long_m = format_money(row['long_pnl'])
        short_m = format_money(row['short_pnl'])
        comm_m = format_money(row['commission'])
        prefix = (
            f"| {row['underlying']} | {row['trades']}"
            f" | {row['total_qty']:,.0f}"
            f" | {long_m} | {short_m} | {comm_m}"
        )
        if has_unrealized:
            real_m = format_money(row['total_realized'])
            unrl_m = format_money(row['unrealized'])
            total_m = format_money(row['total_pnl'], bold=True)
            lines.append(
                f"{prefix}"
                f" | {real_m} | {unrl_m} | {total_m} |"
            )
        else:
            real_m = format_money(
                row['total_realized'], bold=True
            )
            lines.append(f"{prefix} | {real_m} |")

    grand_total_realized = grand_total_pnl + grand_total_commission
    grand_total = grand_total_realized + grand_total_unrealized

    gt_long = format_money(grand_total_long_pnl, bold=True)
    gt_short = format_money(grand_total_short_pnl, bold=True)
    gt_comm = format_money(grand_total_commission, bold=True)
    gt_real = format_money(grand_total_realized, bold=True)
    gt_prefix = (
        f"| **TOTAL** | {len(consolidated)}"
        f" | {grand_total_qty:,.0f}"
        f" | {gt_long} | {gt_short} | {gt_comm}"
    )
    if has_unrealized:
        gt_unrl = format_money(grand_total_unrealized, bold=True)
        gt_total = format_money(grand_total, bold=True)
        lines.append(
            f"{gt_prefix}"
            f" | {gt_real} | {gt_unrl} | {gt_total} |"
        )
    else:
        lines.append(f"{gt_prefix} | {gt_real} |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # Detail by underlying
    lines.append("## Detail by Underlying")
    lines.append("")

    for underlying in sorted(by_underlying.keys()):
        rows = by_underlying[underlying]
        lines.append(f"### {underlying}")
        lines.append("")

        long_pnl = sum(
            r.get("FifoPnlRealized", 0) for r in rows if r.get("Position") == "CLOSE_LONG"
        )
        short_pnl = sum(
            r.get("FifoPnlRealized", 0) for r in rows if r.get("Position") == "CLOSE_SHORT"
        )
        total_symbol_pnl = sum(r.get("FifoPnlRealized", 0) for r in rows)

        long_opens = len([r for r in rows if r.get("Position") == "LONG"])
        long_closes = len([r for r in rows if r.get("Position") == "CLOSE_LONG"])
        short_opens = len([r for r in rows if r.get("Position") == "SHORT"])
        short_closes = len([r for r in rows if r.get("Position") == "CLOSE_SHORT"])

        lines.append("#### P&L Summary")
        lines.append("")
        lines.append("| Position Type | Trades | Realized P&L |")
        lines.append("|---------------|--------|--------------|")
        lines.append(
            f"| Long (open/close) | {long_opens}/{long_closes} | {format_money(long_pnl)} |"
        )
        lines.append(
            f"| Short (open/close) | {short_opens}/{short_closes} | {format_money(short_pnl)} |"
        )
        lines.append(f"| **Total** | {len(rows)} | {format_money(total_symbol_pnl, bold=True)} |")
        lines.append("")

        lines.append("#### Trades (by Date)")
        lines.append("")
        lines.append("| Date | Strike | Type | Position | Qty | Net Cash | P&L |")
        lines.append("|------|--------|------|----------|-----|----------|-----|")

        sorted_rows = sorted(rows, key=lambda x: (x.get("TradeDate", ""), x.get("Symbol", "")))

        for row in sorted_rows:
            trade_date = format_date(row.get("TradeDate", ""))
            strike = row.get("Strike", "")
            put_call = row.get("Put/Call", "")
            position = row.get("Position", "")
            qty = row.get("Quantity", 0)
            net_cash = row.get("NetCash", 0)
            pnl = row.get("FifoPnlRealized", 0)

            lines.append(
                f"| {trade_date} | {strike} | {put_call} | {position} | "
                f"{qty:,.0f} | {format_money(net_cash)} | {format_money(pnl)} |"
            )

        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(f"*Report generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Markdown report saved to: {output_path}")


def generate_csv(consolidated: list[dict], output_path: Path):
    """Generate CSV report."""
    if not consolidated:
        print("No data to write to CSV")
        return

    columns = KEEP_COLS + GROUP_COLS + ["Position"] + AGG_COLS

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(consolidated)

    print(f"CSV report saved to: {output_path}")

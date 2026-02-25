# ABOUTME: Consolidates IBRK trade CSV files by grouping and aggregating.
# ABOUTME: Groups trades by symbol, underlying, date, strike, buy/sell, and open/close.

import asyncio
import csv
from pathlib import Path

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
        from trading_skills.broker.connection import (
            CLIENT_IDS,
            fetch_positions,
            ib_connection,
        )
    except ImportError:
        print("Warning: ib_async not available, skipping unrealized P&L")
        return {}, None

    # Determine ports to try
    if port:
        ports_to_try = [port]
    else:
        ports_to_try = [7496, 7497]  # Try live first, then paper

    ib_ctx = None
    connected_port = None
    for try_port in ports_to_try:
        try:
            print(f"Trying to connect to IB on port {try_port}...")
            ib_ctx = ib_connection(try_port, CLIENT_IDS["consolidate"])
            ib = await ib_ctx.__aenter__()
            connected_port = try_port
            print(f"Connected to IB on port {try_port}")
            break
        except ConnectionError as e:
            print(f"  Port {try_port} not available: {e}")
            continue

    if not connected_port:
        print("Warning: Could not connect to IB on any port")
        return {}, None

    unrealized_by_symbol = {}
    account_id = None

    try:
        # Get account ID
        managed_accounts = ib.managedAccounts()
        if managed_accounts:
            account_id = managed_accounts[0]
            print(f"Account: {account_id}")

        # Get all positions
        all_positions = await fetch_positions(ib)
        print(f"Found {len(all_positions)} positions in portfolio")

        # Separate options from other positions
        option_positions = [p for p in all_positions if p.contract.secType == "OPT"]

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
        await ib_ctx.__aexit__(None, None, None)

    return unrealized_by_symbol, account_id

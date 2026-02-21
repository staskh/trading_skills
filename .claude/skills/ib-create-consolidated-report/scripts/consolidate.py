#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IBRK trade CSV consolidation.
# ABOUTME: Groups trades by symbol, underlying, date, strike, buy/sell, and open/close.

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from trading_skills.broker.consolidate import (
    consolidate_rows,
    fetch_unrealized_pnl,
    generate_csv,
    generate_markdown,
    read_csv_files,
)


async def main_async(args):
    input_dir = Path(args.directory)

    if not input_dir.is_dir():
        print(f"Error: {input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        script_dir = Path(__file__).parent.parent.parent.parent.parent
        output_dir = script_dir / "sandbox"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate timestamp for filenames
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")

    # Read and consolidate
    print(f"\nReading CSV files from: {input_dir}")
    rows, processed_files = read_csv_files(input_dir)

    if not rows:
        print("No data found to consolidate")
        sys.exit(1)

    print(f"\nTotal rows read: {len(rows)}")
    print("Consolidating...")

    consolidated = consolidate_rows(rows)
    print(f"Consolidated to {len(consolidated)} grouped rows")

    # Fetch unrealized P&L from IB (auto-probe ports if not specified)
    unrealized_pnl, account_id = await fetch_unrealized_pnl(args.port)

    # Generate outputs with account prefix if available
    if account_id:
        md_path = output_dir / f"{account_id}_consolidated_trades_{timestamp}.md"
        csv_path = output_dir / f"{account_id}_consolidated_trades_{timestamp}.csv"
    else:
        md_path = output_dir / f"consolidated_trades_{timestamp}.md"
        csv_path = output_dir / f"consolidated_trades_{timestamp}.csv"

    generate_markdown(consolidated, unrealized_pnl, processed_files, md_path)
    generate_csv(consolidated, csv_path)

    # Output JSON for skill integration
    print(json.dumps({
        "success": True,
        "input_directory": str(input_dir),
        "rows_read": len(rows),
        "rows_consolidated": len(consolidated),
        "has_unrealized_pnl": bool(unrealized_pnl),
        "markdown_report": str(md_path),
        "csv_report": str(csv_path),
    }))


def main():
    parser = argparse.ArgumentParser(
        description="Consolidate IBRK trade CSV files into summary reports"
    )
    parser.add_argument(
        "directory",
        type=str,
        help="Directory containing CSV files to consolidate",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for reports (default: sandbox/)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="IB port to fetch unrealized P&L (7497=paper, 7496=live)",
    )

    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

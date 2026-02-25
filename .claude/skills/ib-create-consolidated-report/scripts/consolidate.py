#!/usr/bin/env python3
# ABOUTME: CLI wrapper for IBRK trade CSV consolidation.
# ABOUTME: Groups trades by symbol, underlying, date, strike, buy/sell, and open/close.

import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from trading_skills.broker.consolidate import (
    AGG_COLS,
    GROUP_COLS,
    KEEP_COLS,
    consolidate_rows,
    fetch_unrealized_pnl,
    read_csv_files,
)
from trading_skills.utils import format_expiry_iso


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

        long_m = format_money(row["long_pnl"])
        short_m = format_money(row["short_pnl"])
        comm_m = format_money(row["commission"])
        prefix = (
            f"| {row['underlying']} | {row['trades']}"
            f" | {row['total_qty']:,.0f}"
            f" | {long_m} | {short_m} | {comm_m}"
        )
        if has_unrealized:
            real_m = format_money(row["total_realized"])
            unrl_m = format_money(row["unrealized"])
            total_m = format_money(row["total_pnl"], bold=True)
            lines.append(f"{prefix} | {real_m} | {unrl_m} | {total_m} |")
        else:
            real_m = format_money(row["total_realized"], bold=True)
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
        lines.append(f"{gt_prefix} | {gt_real} | {gt_unrl} | {gt_total} |")
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
            f"| Short (open/close) | {short_opens}/{short_closes}"
            f" | {format_money(short_pnl)} |"
        )
        lines.append(
            f"| **Total** | {len(rows)} | {format_money(total_symbol_pnl, bold=True)} |"
        )
        lines.append("")

        lines.append("#### Trades (by Date)")
        lines.append("")
        lines.append("| Date | Strike | Type | Position | Qty | Net Cash | P&L |")
        lines.append("|------|--------|------|----------|-----|----------|-----|")

        sorted_rows = sorted(rows, key=lambda x: (x.get("TradeDate", ""), x.get("Symbol", "")))

        for row in sorted_rows:
            trade_date = format_expiry_iso(row.get("TradeDate", ""))
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
    print(
        json.dumps(
            {
                "success": True,
                "input_directory": str(input_dir),
                "rows_read": len(rows),
                "rows_consolidated": len(consolidated),
                "has_unrealized_pnl": bool(unrealized_pnl),
                "markdown_report": str(md_path),
                "csv_report": str(csv_path),
            }
        )
    )


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

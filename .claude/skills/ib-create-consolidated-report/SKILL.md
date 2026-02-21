---
name: ib-create-consolidated-report
description: Consolidate IBRK trade CSV files from a directory into a summary report. Groups trades by symbol, underlying, date, strike, buy/sell, and open/close. Outputs both markdown and CSV.
---

# IB Create Consolidated Report

Reads all CSV files from a given directory (excluding subdirectories), consolidates trade data by key fields, and generates both markdown and CSV reports.

## Instructions

```bash
uv run python scripts/consolidate.py <directory> [--port PORT] [--output-dir OUTPUT_DIR]
```

## Arguments

- `directory` - Path to directory containing IBRK trade CSV files
- `--port` - IB port to fetch unrealized P&L (7497=paper, 7496=live). If not specified, auto-probes both ports (tries 7496 first, then 7497).
- `--output-dir` - Output directory for reports (default: sandbox/)

## Consolidation Logic

Groups trades by:
- **UnderlyingSymbol** - The underlying ticker (e.g., GOOG, CAT)
- **Symbol** - Full option symbol
- **TradeDate** - Date of the trade
- **Strike** - Strike price
- **Put/Call** - Option type (C or P)
- **Buy/Sell** - Trade direction
- **Open/CloseIndicator** - Whether opening or closing

Aggregates:
- **Quantity** - Sum of quantities
- **Proceeds** - Sum of proceeds
- **NetCash** - Sum of net cash
- **IBCommission** - Sum of commissions
- **FifoPnlRealized** - Sum of realized P&L

Adds column:
- **Position** - SHORT (Sell+Open), LONG (Buy+Open), CLOSE_SHORT (Buy+Close), CLOSE_LONG (Sell+Close)

## Output

Generates two files in the output directory:
- `consolidated_trades_YYYY-MM-DD_HHMM.md` - Markdown report with summary tables
- `consolidated_trades_YYYY-MM-DD_HHMM.csv` - CSV with all consolidated data

## Example Usage

```bash
# Consolidate trades from IBRK reports directory
uv run python scripts/consolidate.py "C:\Users\avrah\OneDrive\Business\Trading\IBRK reports\2stastrading2025"

# Specify custom output directory
uv run python scripts/consolidate.py "C:\path\to\reports" --output-dir "C:\output"
```

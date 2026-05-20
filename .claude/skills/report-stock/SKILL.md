---
name: report-stock
description: Generate comprehensive stock analysis report (PDF or markdown) with trend, PMCC, and fundamental analysis
user_invocable: true
arguments:
  - name: symbols
    description: Stock ticker symbol(s) - single or space-separated list (e.g., AAPL or "AAPL MSFT GOOGL")
    required: true
dependencies: ["trading-skills"]
---

# Stock Analysis Report Generator

Generates professional reports with comprehensive stock analysis including trend analysis, PMCC viability, and fundamental metrics. Supports both PDF and markdown output formats.

## Instructions

### Step 1: Gather Data

Run the report script for each symbol:

```bash
uv run python scripts/report.py SYMBOL
```

The script returns detailed JSON with:
- `recommendation` - Overall recommendation with strengths/risks
- `company` - Company info (name, sector, industry, market cap)
- `trend_analysis` - Bullish scanner results (score, RSI, MACD, ADX, SMAs)
- `pmcc_analysis` - PMCC viability (score, LEAPS/short details, metrics)
- `fundamentals` - Valuation, profitability, dividend, balance sheet, earnings history
- `piotroski` - F-Score breakdown with all 9 criteria
- `spread_strategies` - Option spread analysis (vertical spreads, straddle, strangle, iron condor)

### Step 2: Generate Report

**Step 2a — Write markdown**

Read `templates/markdown-template.md` for formatting instructions. Generate a markdown report from the JSON data and save to `sandbox/` as:
```
sandbox/{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.md
```

**Step 2b — Convert to PDF (if requested)**

Invoke the `markdown-to-pdf` skill on the markdown file just created:
```bash
uv run python .claude/skills/markdown-to-pdf/scripts/markdown_to_pdf.py sandbox/{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.md
```
The PDF is written alongside the markdown file with the same basename.

### Step 3: Report Results

After generating the report, tell the user:
1. The recommendation (BUY/HOLD/AVOID)
2. Key strengths and risks
3. The report file path

## Example

```bash
# Single symbol
uv run python scripts/report.py AAPL

# Multiple symbols - run separately
uv run python scripts/report.py AAPL
uv run python scripts/report.py MSFT
```

## Dependencies

This skill aggregates data from:
- `scanner-bullish` for trend analysis
- `scanner-pmcc` for PMCC viability
- `fundamentals` for financial data and Piotroski score


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
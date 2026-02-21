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

Choose output format based on user preference:

**For PDF**: Use the `pdf` skill to create a professionally formatted PDF report from the JSON data.
Read `templates/pdf-template.md` for detailed formatting guidelines including color scheme, typography, table layouts, and section structure.

**For Markdown**: Read `templates/markdown-template.md` for formatting instructions. Generate a markdown report and save to `sandbox/`.

**Filename format**:
- PDF: `{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.pdf`
- Markdown: `{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.md`

**Output location**: Save to `sandbox/` directory

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

## Report Contents

### Pages 1-2: Executive Summary & Trend Analysis
- Color-coded recommendation box (green/yellow/red)
- Company overview table
- Bullish scanner metrics with signal interpretations
- Trend signals list

### Pages 2-3: Fundamental Analysis & Piotroski
- Valuation metrics (P/E, P/B, EPS)
- Profitability (margins, ROE, ROA, growth)
- Dividend & balance sheet (yield, payout ratio, debt)
- Earnings history (up to 8 quarters)
- Piotroski F-Score breakdown (all 9 criteria)

### Pages 3-4: PMCC Viability Analysis
- PMCC score and assessment
- LEAPS option details (strike, delta, spread, liquidity)
- Short call details (strike, delta, spread, liquidity)
- Trade metrics (net debit, yield estimates, capital required)

### Pages 4-5: Option Spread Strategies
- Bull call spread with breakeven and risk/reward
- Bear put spread with breakeven and risk/reward
- Long straddle analysis with move needed %
- Long strangle analysis with breakeven prices
- Iron condor with profit range and max risk

### Final Page: Investment Summary
- Strengths box
- Risk factors box
- Disclaimer footer

## Dependencies

This skill aggregates data from:
- `scanner-bullish` for trend analysis
- `scanner-pmcc` for PMCC viability
- `fundamentals` for financial data and Piotroski score

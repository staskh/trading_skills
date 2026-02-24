---
name: ib-collar
description: Generate tactical collar strategy reports for protecting PMCC positions through earnings or high-risk events. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Tactical Collar

Generate a tactical collar strategy report for protecting PMCC positions through earnings or high-risk events.

## Prerequisites

User must have TWS or IB Gateway running locally with API enabled:
- Paper trading: port 7497
- Live trading: port 7496

## Instructions

### Step 1: Gather Data

```bash
uv run python scripts/collar.py SYMBOL [--port PORT] [--account ACCOUNT]
```

The script returns JSON to stdout with all position and scenario data.

### Step 2: Format Report

Read `templates/markdown-template.md` for formatting instructions. Generate a markdown report from the JSON data and save to `sandbox/`.

### Step 3: Report Results

Present key findings to the user: recommended put protection, cost/benefit, and the saved report path.

## Arguments

- `SYMBOL` - Stock symbol to analyze (must be in portfolio)
- `--port` - IB port (default: 7496 for live trading)
- `--account` - Specific account ID (optional, searches all accounts)

## JSON Output

The script returns JSON with these key fields:
- `symbol`, `current_price` - Basic info
- `long_strike`, `long_expiry`, `long_qty`, `long_cost` - LEAPS position
- `short_positions` - List of short calls
- `is_proper_pmcc`, `short_above_long` - PMCC health flags
- `earnings_date`, `days_to_earnings` - Earnings timing
- `put_analysis` - List of put scenarios with costs and P&L under gap up/flat/down
- `unprotected_loss_10`, `unprotected_loss_15`, `unprotected_gain_10` - LEAPS risk without collar
- `volatility` - Historical volatility data

### Report Sections

1. **Position Summary**: Current PMCC structure (long calls, short calls)
2. **PMCC Health Check**: Is structure proper (short > long strike) or broken?
3. **Earnings Risk**: Next earnings date and days until event
4. **Put Duration Analysis**: Comparison of short vs medium vs long-dated puts
5. **Collar Scenarios**: Gap up, flat, gap down outcomes with each put duration
6. **Cost/Benefit Analysis**: Insurance cost vs protection value
7. **Implementation Timeline**: Step-by-step checklist with dates
8. **Recommendation**: Optimal put strike and expiration

### Key Concepts

**Proper PMCC Structure**:
- Long deep ITM LEAPS call
- Short OTM calls ABOVE long strike
- No additional margin required for collar

**Broken PMCC Structure**:
- Long call is now OTM (after crash)
- Short calls BELOW long strike require margin
- Collar still works but margin implications exist

**Tactical Collar**:
- Buy protective puts ONLY before high-risk events (earnings)
- Sell puts after event passes
- Balances income generation with crash protection

**Put Duration Trade-offs**:
- Short-dated: Cheaper, more gamma, but zero salvage on gap up
- Medium-dated (2-4 weeks): Best balance of cost, gamma, and salvage
- Long-dated: Preserves value on gap up, but expensive and less gamma

## Example Usage

```bash
# Analyze NVDA position (defaults to production port 7496)
uv run python scripts/collar.py NVDA

# Analyze specific account
uv run python scripts/collar.py AMZN --account U790497

# Use paper trading port instead
uv run python scripts/collar.py NVDA --port 7497
```

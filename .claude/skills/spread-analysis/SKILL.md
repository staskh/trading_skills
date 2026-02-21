---
name: spread-analysis
description: Analyze option spread strategies like vertical spreads, iron condors, straddles, strangles. Use when user asks about spreads, multi-leg strategies, vertical spread, iron condor, straddle, strangle, or strategy analysis.
---

# Spread Analysis

Analyze multi-leg option strategies.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/spreads.py SYMBOL --strategy STRATEGY --expiry YYYY-MM-DD [options]
```

## Strategies and Options

**Vertical Spread** (bull/bear call/put spread):
```bash
uv run python scripts/spreads.py AAPL --strategy vertical --expiry 2026-01-16 --type call --long-strike 180 --short-strike 185
```

**Straddle** (long call + long put at same strike):
```bash
uv run python scripts/spreads.py AAPL --strategy straddle --expiry 2026-01-16 --strike 180
```

**Strangle** (long call + long put at different strikes):
```bash
uv run python scripts/spreads.py AAPL --strategy strangle --expiry 2026-01-16 --put-strike 175 --call-strike 185
```

**Iron Condor** (sell strangle + buy wider strangle):
```bash
uv run python scripts/spreads.py AAPL --strategy iron-condor --expiry 2026-01-16 --put-short 175 --put-long 170 --call-short 185 --call-long 190
```

## Output

Returns JSON with:
- `strategy` - Strategy name and legs
- `cost` - Net debit or credit
- `max_profit` - Maximum potential profit
- `max_loss` - Maximum potential loss
- `breakeven` - Breakeven price(s)
- `probability` - Estimated probability of profit (based on IV)

Explain the risk/reward and when this strategy is appropriate.

## Dependencies

- `pandas`
- `yfinance`

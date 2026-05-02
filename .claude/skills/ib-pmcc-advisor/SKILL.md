---
name: ib-pmcc-advisor
description: Analyze PMCC (Poor Man's Covered Call / diagonal spread) positions from IB portfolio. For each diagonal spread, reports short leg risk (delta, IV, assignment probability), daily P&L projections, top-3 roll candidates, and a side-by-side comparison table. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB PMCC Advisor

Analyzes all PMCC (diagonal call spread) positions in the IB portfolio and provides actionable advice on the short leg: assignment risk, P&L projections per day, and ranked roll recommendations.

## Prerequisites

TWS or IB Gateway running locally with API enabled:
- Live trading: port 7496
- Paper trading: port 7497

## Instructions

### Step 1: Run the report script

```bash
uv run python .claude/skills/ib-pmcc-advisor/scripts/pmcc_advisor.py [--port PORT] [--account ACCOUNT] [--min-roll-dte N] [--price-mode mid|last]
```

The script returns JSON to stdout. Capture it and format the report.

### Step 2: Format and save the report

Read `.claude/skills/ib-pmcc-advisor/templates/markdown-template.md` for full formatting instructions.

Generate a markdown report from the JSON and save to `sandbox/`:
- Filename: `pmcc_advisor_{ACCOUNT}_{YYYY-MM-DD}_{HHmm}.md`
- Use first account ID. Derive date/time from `generated_at`.

The report must include all sections per spread:
1. **Red flags summary** — assignment > 40%, DTE < 7, no rolls, earnings warnings
2. **Spread structure table** — both legs: strike, expiry, DTE, cost, current price, IV
3. **Short leg risk** — delta (BS + IB), assignment probability with risk label
4. **Daily P&L projections** — all rows: date, days to expiry, best exit spot, max P&L (mark the peak row)
5. **Roll candidates table** — strike, expiry, DTE, delta, assign%, IV, net credit, $/day, P&L if assigned, bid/ask
6. **Comparison table** — current vs roll_1/2/3 side by side
7. **Recommendation** — hold/roll/close with reasoning

### Step 3: Report to user

- State the file path of the saved report.
- Lead with any red flags from the summary section.
- For each spread with a red flag or earnings warning, show the comparison table inline.
- State the top recommendation for each flagged spread.

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 7496 | IB Gateway/TWS port |
| `--account` | all | Specific account ID |
| `--min-roll-dte` | 7 | Minimum DTE for roll candidates |
| `--price-mode` | mid | Option price: `mid` (bid+ask)/2 or `last` |
| `--symbols` | all | Analyze only these symbols (e.g. `--symbols NVDA WMT`) |

## JSON Output Structure

```json
{
  "generated_at": "2026-04-30 10:25 ET",
  "data_delay": "real-time",
  "accounts": ["Uxxxxxxxx"],
  "price_mode": "mid",
  "min_roll_dte": 7,
  "symbols_filter": ["NVDA", "WMT"],
  "spreads": [
    {
      "symbol": "NVDA",
      "account": "Uxxxxxxxx",
      "qty": 10,
      "underlying_price": 201.46,
      "leaps_expiry": "20260918",
      "earnings": {
        "date": "2026-05-20",
        "timing": "AMC",
        "warning_short": false,
        "warning_roll_indices": [1, 2, 3]
      },
      "long": {
        "strike": 180.0, "expiry": "20260918", "dte": 141,
        "avg_cost": 35.51, "current_price": 36.20,
        "iv_pct": 42.1, "ib_delta": 0.7821, "ib_iv_pct": 41.8
      },
      "short": {
        "strike": 210.0, "expiry": "20260618", "dte": 49,
        "premium_received": 6.88, "current_price": 5.10,
        "iv_pct": 38.5, "delta": 0.3421, "assignment_prob_pct": 28.4,
        "ib_delta": 0.3415, "ib_iv_pct": 38.2
      },
      "daily_pnl": [
        {"date": "2026-04-30", "days_to_short_expiry": 49.0, "optimal_spot": 215.20, "pnl": 1234.56},
        {"date": "2026-05-01", "days_to_short_expiry": 48.0, "optimal_spot": 214.80, "pnl": 1289.10}
      ],
      "roll_candidates": [
        {
          "strike": 215.0, "expiry": "20260717", "dte": 78,
          "price": 5.80, "delta": 0.2910, "assignment_prob": 22.5,
          "iv_pct": 37.2, "net_credit": 0.70, "profit_per_day": 0.0744,
          "pnl_if_assigned": 3580.0, "bid": 5.60, "ask": 6.00
        }
      ],
      "comparison": {
        "current":  {"strike": 210, "expiry": "20260618", "dte": 49, "delta": 0.3421, "assignment_prob": 28.4, "profit_per_day": 0.1404, "pnl_if_assigned": 1880.0},
        "roll_1":   {"strike": 215, "expiry": "20260717", "dte": 78, "delta": 0.2910, "assignment_prob": 22.5, "profit_per_day": 0.0744, "pnl_if_assigned": 3580.0}
      }
    }
  ]
}
```

## Key Fields

- `symbols_filter` — list of uppercase symbols when `--symbols` was used; `null` means full portfolio
- `data_delay` — `"real-time"` if live quotes available, `"stalled - using last price"` if IBKR quotes unavailable
- `generated_at` — NY timezone timestamp
- `leaps_expiry` — expiry of the long leg (YYYYMMDD); all roll candidates are capped at or before this date
- `earnings.date` — next earnings date (YYYY-MM-DD) from Yahoo Finance; null for ETFs
- `earnings.timing` — `"BMO"` (before open) or `"AMC"` (after close)
- `earnings.warning_short` — true if earnings fall within the last 7 calendar days before short expiry
- `earnings.warning_roll_indices` — 1-based indices of roll candidates whose expiry window contains the earnings date
- `delta` / `ib_delta` — BS-calculated vs. IBKR model Greeks (both reported when available)
- `iv_pct` / `ib_iv_pct` — IV in percent; BS-calculated from option price vs. IBKR model Greeks
- `assignment_prob_pct` — N(d2): risk-neutral probability the short expires ITM
- `net_credit` — credit received when rolling (negative = debit); rolls with debit > $0.10/share excluded
- `pnl_if_assigned` — P&L if underlying finishes above short_strike at expiry: `(short_strike - long_strike - long_cost + total_premium) × 100`
- `daily_pnl[].optimal_spot` — spot price that maximises exit P&L on that day (found via numerical optimisation); increases as theta decays the short leg
- `daily_pnl[].pnl` — total dollars (qty × 100 contracts) at the optimal spot on that day

## Roll Selection Criteria

Candidates must satisfy both:
1. **Lower delta** than current short (less assignment risk)
2. **Net credit ≥ -$0.10/share** (not a large debit)

Ranked by: delta improvement (highest weight) → net credit → DTE extension.

## Example Usage

```bash
# All accounts, live port
uv run python .claude/skills/ib-pmcc-advisor/scripts/pmcc_advisor.py --port 7496

# Specific account, 14-day minimum roll DTE, last-price mode
uv run python .claude/skills/ib-pmcc-advisor/scripts/pmcc_advisor.py --port 7496 --account Uxxxxxxxx --min-roll-dte 14 --price-mode last

# Analyze only specific symbols
uv run python .claude/skills/ib-pmcc-advisor/scripts/pmcc_advisor.py --port 7496 --symbols NVDA WMT
```

## Architecture

All logic lives in `src/trading_skills/broker/pmcc_advisor.py`:
- **Analytics functions** (top half, no IBKR imports): `get_option_price`, `calc_iv`, `calc_delta`, `calc_assignment_prob`, `calc_bs_price`, `calc_daily_pnl_table`, `check_earnings_warning`, `find_best_rolls`, `build_comparison_table`, `score_roll_candidate`
- **Data layer** (bottom half, uses IBKR + Yahoo Finance): `get_pmcc_data`, `_identify_pmcc_spreads`, `_fetch_single_option_quote`, `_fetch_option_quotes_batch`, `_get_chain_params`, `_fetch_earnings_dates`

Reuses from `src/trading_skills/broker/`:
- `connection.py` — `ib_connection`, `CLIENT_IDS`, `fetch_positions`, `fetch_spot_prices`, `normalize_positions`, `best_option_chain`
- `black_scholes.py` — `implied_volatility`, `black_scholes_price`, `black_scholes_delta`, `estimate_iv`

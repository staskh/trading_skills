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

### Step 2: Format and present results

For each spread in `spreads[]`, present:

1. **Short leg risk summary** — delta, assignment probability, IV (BS-calculated and IBKR-reported)
2. **Daily P&L table** — from today through short expiry: date, days remaining, P&L at optimal spot (= short_strike)
3. **Roll candidates** — top 3 rolls meeting criteria: lower delta AND net credit ≥ -$0.10/share
4. **Comparison table** — current vs. roll_1/2/3: delta, assignment prob, profit/day, P&L if assigned

### Step 3: Report to user

- Lead with any red flags: high assignment probability (>40%), very short DTE (<5 days), or no viable rolls
- Show the comparison table for each spread
- Recommend the best roll if one exists

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 7496 | IB Gateway/TWS port |
| `--account` | all | Specific account ID |
| `--min-roll-dte` | 7 | Minimum DTE for roll candidates |
| `--price-mode` | mid | Option price: `mid` (bid+ask)/2 or `last` |

## JSON Output Structure

```json
{
  "generated_at": "2026-04-30 10:25 ET",
  "data_delay": "real-time",
  "accounts": ["Uxxxxxxxx"],
  "price_mode": "mid",
  "min_roll_dte": 7,
  "spreads": [
    {
      "symbol": "NVDA",
      "account": "Uxxxxxxxx",
      "qty": 10,
      "underlying_price": 201.46,
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
        {"date": "2026-04-30", "days_to_short_expiry": 49, "optimal_spot": 210.0, "pnl": 1234.56},
        ...
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

- `data_delay` — `"real-time"` if live quotes available, `"stalled - using estimated IV"` if IBKR quotes unavailable
- `generated_at` — NY timezone timestamp
- `delta` / `ib_delta` — BS-calculated vs. IBKR model Greeks (both reported when available)
- `iv_pct` / `ib_iv_pct` — IV in percent; BS-calculated from option price vs. IBKR model Greeks
- `assignment_prob_pct` — N(d2): risk-neutral probability the short expires ITM
- `net_credit` — credit received when rolling (negative = debit); rolls with debit > $0.10/share excluded
- `pnl_if_assigned` — P&L per contract if underlying is above short_strike at expiry: `(short_strike - long_strike - long_cost + total_premium) × 100`
- `optimal_spot` in `daily_pnl` — always equals short_strike (highest P&L achievable without assignment risk)

## Roll Selection Criteria

Candidates must satisfy both:
1. **Lower delta** than current short (less assignment risk)
2. **Net credit ≥ -$0.10/share** (not a large debit)

Ranked by: delta improvement (highest weight) → net credit → DTE extension.

## Example Usage

```bash
# All accounts, live port
uv run python .claude/skills/ib-pmcc-advisor/scripts/report.py --port 7496

# Specific account, 14-day minimum roll DTE, last-price mode
uv run python .claude/skills/ib-pmcc-advisor/scripts/report.py --port 7496 --account Uxxxxxxxx --min-roll-dte 14 --price-mode last
```

## Architecture

All logic lives in `src/trading_skills/broker/pmcc_advisor.py`:
- **Analytics functions** (top half, no IBKR imports): `get_option_price`, `calc_iv`, `calc_delta`, `calc_assignment_prob`, `calc_bs_price`, `calc_daily_pnl_table`, `find_best_rolls`, `build_comparison_table`, `score_roll_candidate`
- **Data layer** (bottom half, uses IBKR): `get_pmcc_data`, `_identify_pmcc_spreads`, `_fetch_single_option_quote`, `_fetch_option_quotes_batch`, `_get_chain_params`

Reuses from `src/trading_skills/broker/`:
- `connection.py` — `ib_connection`, `CLIENT_IDS`, `fetch_positions`, `fetch_spot_prices`, `normalize_positions`, `best_option_chain`
- `black_scholes.py` — `implied_volatility`, `black_scholes_price`, `black_scholes_delta`, `estimate_iv`

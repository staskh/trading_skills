---
name: ib-stop-loss
description: Downside stop-loss management for PMCC, naked LEAPS, and stock positions in IB. Computes stop prices, detects alerts, and places conditional combo orders. Dry-run by default. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Stop-Loss Manager

Analyzes PMCC (diagonal call spread), naked LEAPS, and stock positions in the IB portfolio and manages conditional stop-loss orders.

**Default mode is dry-run** — no orders are placed unless `--execute` is in the request.

## Prerequisites

TWS or IB Gateway running locally with API enabled:
- Live trading: port 7496
- Paper trading: port 7497

## Instructions

### Step 1: Run the script

Dry-run (default — no orders placed):
```bash
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496
```

Execute (cancel orphan orders + place SL_ conditional orders):
```bash
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496 --execute
```

Execute forced (basis = current mid price, can lower existing stops):
```bash
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496 --execute --forced
```

### Step 2: Format the report

Format JSON output as a markdown report with four sections:

#### Section 1: Alert Soon
List symbols in `alert_soon` prominently — these are past the early-warning threshold.

#### Section 2: Existing Conditional Orders
Show `all_conditional_orders.module` (SL_ orders) and `all_conditional_orders.manual` (manually placed).
If `orphan_orders` is non-empty, warn that these were cancelled (execute mode) or need manual cancellation (dry-run).

#### Section 3: Positions
For each entry in `positions`, show a table:

| Field | Value |
|---|---|
| Symbol | NVDA — pmcc (3 contracts) |
| Spot | $219.05 |
| LEAPS | 200C 20270115 · avg cost $44.27 · current $44.23 · basis $44.27 |
| **Stop price** | $22.14 (40% stop) → action: place_new |
| LEAPS loss | 0.1% |
| Shorts | 235C 20260515 · received $0.61 · current $0.56 · 9.5% decayed |

Show `preserve_existing` when a more-protective stop already exists.
Show `overwrite` (red) when `forced=true` lowers an existing stop.

#### Section 4: Alerts
Group alerts by symbol. Types:

| Type | Meaning |
|---|---|
| `leaps_early_warning` | LEAPS down ≥ stop_pct/2% from basis |
| `short_premium_decay` | 90%+ of short premium captured — close or roll |
| `short_near_strike` | Spot at/above or within X% of short strike |

### Step 3: Report to user

- State dry-run vs execute mode prominently.
- Lead with `alert_soon` symbols.
- For each position: show stop action and current loss %.
- Show alerts section last.

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 7496 | IB Gateway/TWS port |
| `--account` | all | Specific account ID |
| `--symbols` | all | Analyze only these symbols |
| `--legs` | none | Specific option legs: `SYMBOL:STRIKE[C\|P]:EXPIRY` (e.g. `IBKR:70C:20270115 IBKR:100C:20260918`). Right defaults to `C`. Takes precedence over `--symbols`. Use when multiple PMCC/LEAPS coexist on the same symbol and only one pairing should get a stop. |
| `--stop-pct` | 40 | Loss % that triggers exit |
| `--short-near-strike-pct` | 5 | Near-strike alert threshold |
| `--price-mode` | mid | Option pricing: `mid` or `last` |
| `--execute` | off | Cancel orphans + place SL_ orders |
| `--forced` | off | Use current mid as basis (requires `--execute`) |

## JSON Output Structure

```json
{
  "generated_at": "2026-05-12 10:00 ET",
  "dry_run": true,
  "forced": false,
  "stop_pct": 40.0,
  "short_near_strike_pct": 5.0,
  "accounts": ["U1234567"],
  "symbols_filter": null,
  "all_conditional_orders": {"module": [], "manual": []},
  "orphan_orders": [],
  "alert_soon": ["PFE"],
  "positions": [
    {
      "symbol": "NVDA",
      "type": "pmcc",
      "account": "U1234567",
      "qty": 3,
      "underlying_price": 219.05,
      "leaps": {
        "strike": 200.0, "expiry": "20270115", "avg_cost": 44.27,
        "current_price": 44.23, "stop_basis": 44.27,
        "stop_price": 22.14, "loss_pct": 0.1
      },
      "shorts": [
        {"strike": 235.0, "expiry": "20260515",
         "premium_received": 0.61, "current_price": 0.56, "decay_pct": 9.5}
      ],
      "stop_loss": {"stop_price": 22.14, "action": "place_new", "existing_stop": null},
      "alert_soon": false,
      "alerts": []
    },
    {
      "symbol": "AAPL",
      "type": "stock",
      "account": "U1234567",
      "qty": 100,
      "underlying_price": 189.50,
      "stock": {
        "avg_cost": 175.00, "stop_basis": 189.50,
        "stop_price": 94.75, "loss_pct": 0.0
      },
      "stop_loss": {"stop_price": 94.75, "action": "place_new", "existing_stop": null},
      "alert_soon": false,
      "alerts": []
    }
  ]
}
```

## Key Fields

- `alert_soon` — top-level list of symbols where loss ≥ stop_pct/2%
- `position.type` — `pmcc` | `leaps` | `stock`
- `stop_loss.action` — `place_new` | `preserve_existing` | `overwrite`
- `stop_loss.existing_stop` — price of the existing SL_FALL_ order if present
- For PMCC: stop order is a single combo (BAG) order closing LEAPS + all shorts atomically
- In execute mode: orphan SL_ orders (no matching position) are cancelled first

## Order Identification

- `SL_FALL_{SYM}_{STRIKE}_{EXPIRY}` — options (PMCC or naked LEAPS)
- `SL_FALL_{SYM}_STK` — stock positions

## Architecture

All analytics live in `src/trading_skills/broker/stop_loss.py`:

**Analytics (no IBKR — testable in isolation):**
- `calc_stop_basis` — max(mid, avg_cost) normally; current_mid if forced
- `calc_stop_price` — basis × (1 - stop_pct/100)
- `calc_short_premium_decay_pct` — % of short premium captured
- `identify_positions` — classify normalized positions into pmcc/leaps/stock
- `build_position_analysis` — full per-position output dict
- `detect_orphan_orders` — SL_FALL_ orders for gone positions
- `summarize_all_conditional_orders` — splits IB orders into module vs manual

**Data layer (IBKR):**
- `get_stop_loss_data` — main entry point
- `_cancel_orphan_orders` — cancel stale SL_ orders
- `_place_combo_stop_order` — BAG order for PMCC (atomic LEAPS + shorts)
- `_place_simple_stop_order` — single order for naked LEAPS or stock
- `_execute_position_stop` — dispatch per position type

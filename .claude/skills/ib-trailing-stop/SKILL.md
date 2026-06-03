---
name: ib-trailing-stop
description: Server-side trailing stop management for stocks and naked LEAPS in IB. Places native TRAIL orders that auto-ratchet the stop as price climbs. Dry-run by default. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Trailing Stop Manager

Places IB native **TRAIL** orders against stocks and naked LEAPS in the portfolio.
IB auto-adjusts the stop trigger as the price climbs and locks it as price falls.

PMCC positions are intentionally excluded — use `ib-stop-loss` for those (a standalone
trailing stop on the PMCC long leg would break the hedge at trigger).

**Default mode is dry-run** — no orders are placed unless `--execute` is in the request.

## Prerequisites

TWS or IB Gateway running locally with API enabled:
- Live trading: port 7496
- Paper trading: port 7497

## Instructions

### Step 1: Run the script

Dry-run (default — no orders placed):
```bash
uv run python .claude/skills/ib-trailing-stop/scripts/trailing_stop.py --port 7496 --symbols JOBY --trail-pct 20
```

Execute (cancel orphan TS_ orders + place new TS_ TRAIL orders):
```bash
uv run python .claude/skills/ib-trailing-stop/scripts/trailing_stop.py --port 7496 --symbols JOBY --trail-pct 20 --execute
```

Execute forced (cancel + replace existing TS_ orders with current parameters):
```bash
uv run python .claude/skills/ib-trailing-stop/scripts/trailing_stop.py --port 7496 --execute --forced
```

### Step 2: Format the report

Format JSON output as a markdown report with three sections:

#### Section 1: Existing TRAIL Orders
Show `all_trail_orders.module` (TS_ orders) and `all_trail_orders.manual` (manually placed).
If `orphan_orders` is non-empty, warn that these were cancelled (execute mode) or need manual cancellation (dry-run).

#### Section 2: Positions
For each entry in `positions`, show a table:

| Field | Value |
|---|---|
| Symbol | JOBY — stock (1000 shares) |
| Spot | $7.50 |
| Reference | $7.50 (max of current $7.50, avg cost $5.00) |
| **Trail params** | 20% (initial stop $6.00) → action: place_new |
| Existing trail | none |

For LEAPS rows, also show the option leg (strike/expiry) and current option mark.

`action` values:
- `place_new` — no existing TS_ order; one will be created in execute mode
- `preserve_existing` — TS_ already in place; left alone (IB has been tracking the high)
- `overwrite` — `--forced` is on; existing TS_ will be cancelled and replaced

#### Section 3: Order Results (execute mode only)
Per-position result with `order_id` and `order_ref`.

### Step 3: Report to user

- State dry-run vs execute mode prominently.
- Lead with positions that have `action: place_new` (these are about to get a new TRAIL).
- Call out `preserve_existing` separately so user knows nothing changed.
- Show existing trail details (current `trail_stop_price`) so user knows where IB has trailed to.

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 7496 | IB Gateway/TWS port |
| `--account` | all | Specific account ID |
| `--symbols` | all | Analyze only these symbols |
| `--trail-pct` | 20 | Trail amount as percentage of reference |
| `--trail-amt` | — | Trail amount in dollars (mutually exclusive with --trail-pct) |
| `--price-mode` | mid | Option pricing: `mid` or `last` (LEAPS only) |
| `--execute` | off | Cancel orphans + place TS_ TRAIL orders |
| `--forced` | off | Cancel and replace existing TS_ orders (requires `--execute`) |

## JSON Output Structure

```json
{
  "generated_at": "2026-05-29 10:00 ET",
  "data_delay": "real-time",
  "dry_run": true,
  "forced": false,
  "trail_pct": 20.0,
  "trail_amt": null,
  "accounts": ["U1234567"],
  "symbols_filter": ["JOBY"],
  "all_trail_orders": {"module": [], "manual": []},
  "orphan_orders": [],
  "positions": [
    {
      "symbol": "JOBY",
      "type": "stock",
      "account": "U1234567",
      "qty": 1000,
      "underlying_price": 7.50,
      "stock": {
        "avg_cost": 5.00,
        "current_price": 7.50
      },
      "trail_stop": {
        "trail_pct": 20.0,
        "trail_amt": null,
        "reference": 7.50,
        "initial_stop_price": 6.00,
        "action": "place_new",
        "existing_trail": null
      }
    }
  ]
}
```

## Key Behaviors

- **Reference price** = `max(current_price, avg_cost)` — locks in profit when above cost, never starts below entry.
- **Forced mode** uses `current_price` as the reference (can place an initial stop below entry, useful when re-arming after a drawdown).
- **Existing TS_ orders are preserved by default** because IB has been ratcheting the trail since placement — replacing would reset that tracked high. Use `--forced` to deliberately reset.
- **Scope**: stocks + naked LEAPS only. PMCC positions are excluded; use `ib-stop-loss` for those.

## Order Identification

- `TS_{SYM}_{STRIKE}_{EXPIRY}_{RIGHT}` — naked LEAPS TRAIL orders (right is `C` or `P` so calls and puts on the same strike/expiry don't collide)
- `TS_{SYM}_STK` — stock TRAIL orders

## Architecture

All analytics live in `src/trading_skills/broker/trailing_stop.py`:

**Analytics (no IBKR — testable in isolation):**
- `calc_trail_reference` — `max(current_price, avg_cost)` normally; `current_price` if forced
- `calc_initial_trail_stop_price` — reference × (1 − trail_pct/100) or reference − trail_amt
- `identify_trailable_positions` — stocks + naked LEAPS; PMCC excluded
- `build_trail_analysis` — full per-position output dict
- `detect_orphan_trail_orders` — TS_ TRAIL orders for gone positions
- `summarize_all_trail_orders` — splits IB TRAIL orders into module vs manual

**Data layer (IBKR):**
- `get_trailing_stop_data` — main entry point
- `_cancel_orphan_orders` — cancel stale TS_ orders
- `_place_simple_trail_order` — native TRAIL order on stock or option
- `_execute_position_trail` — dispatch per position type

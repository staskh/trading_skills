---
name: ib-stop-loss
description: Manage stop-loss conditional orders for PMCC (diagonal spread) positions from IB portfolio. Computes delta-neutral rising watermark, LEAPS loss stop price, and three alert conditions. Dry-run by default. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB Stop-Loss Manager

Analyzes all PMCC (diagonal call spread) positions in the IB portfolio and manages conditional stop-loss orders with two exit triggers and three alert conditions.

**Default mode is dry-run** — no orders are placed unless `EXECUTE` is in the request.

## Prerequisites

TWS or IB Gateway running locally with API enabled:
- Live trading: port 7496
- Paper trading: port 7497

## Instructions

### Step 1: Run the script

```bash
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py [OPTIONS]
```

Dry-run (default — no orders placed):
```bash
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496
```

Execute (submit conditional orders, preserve existing higher watermarks):
```bash
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496 --execute
```

Execute forced (overwrite all existing watermarks):
```bash
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496 --execute --forced
```

### Step 2: Format the report

The script returns JSON to stdout. Format it as a markdown report with three sections:

#### Section 1: Orphan Orders
If `orphan_orders` is non-empty, list them with a warning. These are conditional orders for positions that no longer exist and should be cancelled.

#### Section 2: Stop-Loss Actions
For each entry in `stop_actions`, show a table:

| Field | Value |
|---|---|
| Symbol | NVDA (10 contracts) |
| Spot | $201.46 |
| **Rising watermark** | $218.50 → action: place_new |
| Existing watermark | — |
| **LEAPS stop price** | $18.10 (basis $36.20, 50% stop) |
| Current LEAPS loss | 0.0% |
| LEAPS stop action | place_new |
| Existing stop | — |

Show `preserve_existing` in amber when a higher watermark is being preserved.
Show `overwrite` in red when `forced=true` overwrites a higher watermark.

#### Section 3: Alerts
List all alerts grouped by symbol. Alert types and their meaning:

| Type | Meaning |
|---|---|
| `short_premium_decay` | 90%+ of short premium captured — consider closing or rolling |
| `short_near_strike` | Short bid is at/below X% of strike — spot nearing short strike |
| `leaps_early_warning` | LEAPS down stop_pct/2% — early warning before stop fires |

### Step 3: Report to user

- State dry-run vs execute mode prominently.
- Lead with any orphan orders.
- For each spread: show the action (place_new / preserve_existing / overwrite / no_watermark).
- Show all alerts in a separate section at the end.
- State the file path if a report was saved.

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `--port` | 7496 | IB Gateway/TWS port |
| `--account` | all | Specific account ID |
| `--symbols` | all | Analyze only these symbols |
| `--stop-pct` | 50 | LEAPS loss % that triggers exit |
| `--short-near-strike-pct` | 10 | Alert when short price ≤ X% of strike |
| `--price-mode` | mid | Option pricing: `mid` or `last` |
| `--execute` | off | Submit conditional orders to IB |
| `--forced` | off | Overwrite existing watermarks (requires `--execute`) |

## JSON Output Structure

```json
{
  "generated_at": "2026-05-10 10:30 ET",
  "data_delay": "real-time",
  "dry_run": true,
  "forced": false,
  "stop_pct": 50.0,
  "short_near_strike_pct": 10.0,
  "accounts": ["U1234567"],
  "symbols_filter": null,
  "orphan_orders": [],
  "stop_actions": [
    {
      "symbol": "NVDA",
      "account": "U1234567",
      "qty": 10,
      "underlying_price": 201.46,
      "long": {
        "strike": 180.0,
        "expiry": "20260918",
        "dte": 141,
        "avg_cost": 35.51,
        "current_price": 36.20,
        "stop_basis": 36.20,
        "stop_price": 18.10,
        "loss_pct_current": 0.0
      },
      "short": {
        "strike": 210.0,
        "expiry": "20260618",
        "dte": 49,
        "premium_received": 6.88,
        "current_price": 5.10,
        "decay_pct": 25.9
      },
      "rising_watermark": {
        "spot": 218.50,
        "action": "place_new",
        "existing_watermark": null
      },
      "falling_stop": {
        "leaps_stop_price": 18.10,
        "leaps_current_price": 36.20,
        "action": "place_new",
        "existing_stop_price": null
      },
      "alerts": []
    }
  ]
}
```

## Key Fields

- `rising_watermark.spot` — underlying price where long_delta = short_delta (max spread value); `null` if no crossing found
- `rising_watermark.action` — `place_new` | `preserve_existing` | `overwrite` | `no_watermark`
- `falling_stop.leaps_stop_price` — `max(current_leaps_price, avg_cost) × (1 - stop_pct/100)`
- `falling_stop.action` — same action enum as rising_watermark
- `orphan_orders` — SL_ orders whose spread no longer exists in the portfolio
- `order_results` — only present when `dry_run=false`; per-symbol list of submitted order statuses

## Order Identification

Stop-loss orders placed by this module use `orderRef` format:
- `SL_RISE_<SYM>_<STRIKE>_<EXPIRY>` — rising-watermark exit leg
- `SL_FALL_<SYM>_<STRIKE>_<EXPIRY>` — falling-stop exit leg

This prefix allows the module to detect its own orders on subsequent runs and avoid overwriting higher watermarks.

## Example Usage

```bash
# Dry-run all accounts
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496

# Dry-run specific symbols
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496 --symbols NVDA WMT

# Execute with 40% LEAPS stop
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496 --execute --stop-pct 40

# Force overwrite all watermarks
uv run python .claude/skills/ib-stop-loss/scripts/stop_loss.py --port 7496 --execute --forced
```

## Architecture

All analytics live in `src/trading_skills/broker/stop_loss.py`:

**Analytics (no IBKR — testable in isolation):**
- `find_delta_neutral_spot` — brentq search for net-delta=0 crossing
- `calc_leaps_stop_basis` — max(market_price, cost_basis)
- `calc_leaps_stop_price` — basis × (1 - stop_pct/100)
- `calc_short_premium_decay_pct` — % of short premium captured
- `check_alerts` — three alert conditions
- `detect_orphan_orders` — SL_ orders for gone positions
- `build_stop_analysis` — assembles per-spread output dict

**Data layer (IBKR + Yahoo Finance):**
- `get_stop_loss_data` — main entry point
- `_fetch_open_orders` — normalize ib.openTrades()
- `_parse_existing_watermarks` — extract condition prices from SL_ orders
- `_place_conditional_order` — qualify contract + submit PriceCondition order
- `_execute_stop_orders` — orchestrate both legs per spread

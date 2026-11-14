---
name: ib-pmcc-bot
description: Operational PMCC bot — scans for new diagonal (Poor Man's Covered Call) opportunities, opens the top-N that fit available margin as combo orders, and actively manages the short leg (closes + rerolls once the premium has decayed past a threshold). Options only; the long leg is always a long call, never a future. Dry-run by default. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB PMCC Bot (Operational)

Turns the PMCC scanner into an operator. It both **opens** new diagonal call spreads and
**manages** the ones it opened. Read-write: places orders only when `--execute` is passed.

## Safety model

- **Dry-run by default.** Without `--execute` the bot connects, analyzes, and prints the exact
  orders it *would* place — nothing is sent.
- **Paper first.** Default port is `7497` (paper). Promote to live `7496` only after the bot's
  paper proposals prove positive.
- **Manages only its own.** Bot orders are tagged `BOT_PMCC_*` / `BOT_CLOSE_*`. Exit management
  only touches **equity diagonal-call spreads**, so manual futures/stock positions are excluded
  by construction. Never run live without reviewing a dry-run first.
- **Options only.** The long leg is always a long call (LEAPS-style), never a future.

## Instructions

### Step 1 — Dry-run preview (always do this first)

```bash
uv run python .claude/skills/ib-pmcc-bot/scripts/bot.py [SYMBOLS] [--port 7497] [--top-n 3] [--decay-threshold 0.70]
```

Prints JSON with two phases:
- `manage` — existing bot-owned diagonals, each short's decay %, and whether it's `hold` or
  `close_and_reroll`.
- `open` — scanned candidates, the top-N selected to open (with `entry_cost` and combo legs),
  committed capital vs available funds, and `skipped` candidates with reasons.

Present the dry-run to the user. Lead with what would be opened/closed and the capital impact.

### Step 2 — Execute (only after explicit user confirmation)

```bash
uv run python .claude/skills/ib-pmcc-bot/scripts/bot.py [SYMBOLS] --port 7497 --execute
```

Places combo BUY-debit entry orders for the selected diagonals and BUY-to-close orders for
shorts past the decay threshold. Orders are `LMT` at the net debit / current mid.

## Arguments

| Flag | Default | Description |
|------|---------|-------------|
| `SYMBOLS` | mega-cap universe | Comma-separated tickers to scan for new diagonals |
| `--port` | 7497 | IB port (7497 paper, 7496 live) |
| `--account` | first managed | Specific account ID |
| `--top-n` | 3 | Max new diagonals to open per cycle |
| `--min-score` | 0.0 | Minimum PMCC score (out of 14) required to open |
| `--decay-threshold` | 0.70 | Close + reroll the short once this fraction of premium has decayed |
| `--execute` | off | Place real orders. Omit for dry-run preview |

## Operating policy (baked-in defaults)

- **Entry:** top-3 candidates by PMCC score, 1 contract each, gated by available funds.
- **Capital gate:** opens only while cumulative entry debit fits within `AvailableFunds`
  (falls back to `ExcessLiquidity`). Candidates that don't fit are skipped with a reason.
- **Exit:** active management — close the short and reroll once ~70% of the premium has decayed.

## Architecture

Logic lives in `src/trading_skills/broker/pmcc_bot.py`:
- **Pure/testable:** `entry_cost_usd`, `select_entries`, `short_decay_pct`, `should_close_short`,
  `build_entry_plan`, `order_ref_for`.
- **IBKR I/O:** `_available_funds`, `_place_diagonal_combo`, `_place_buy_to_close`, `run_pmcc_bot`.

Reuses `scanner_pmcc.analyze_pmcc` (candidate scoring), `pmcc_advisor` (short-quote fetch,
diagonal identification), and the combo-order pattern from `stop_loss.py`.

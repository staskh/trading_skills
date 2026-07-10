---
name: ib_0dte
description: Find and place the best 0DTE (zero-days-to-expiration) credit spreads from Interactive Brokers for index or stock options. Builds bear call spreads (default), bull put spreads, or iron condors, ranked by probability-weighted expected value within a capital-at-risk budget, then optionally executes the chosen spread as a native combo order. Supports cash-settled indices (SPX, NDX, RUT, VIX) and any optionable stock/ETF. Use when the user asks about 0DTE trades, same-day expiration spreads, or best credit spreads for today. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB 0DTE Credit Spread Finder & Executor

Find the best zero-days-to-expiration credit spreads for an underlying, sized to a
budget and ranked by probability-weighted expected value — then optionally place the
chosen spread as a live order. All data comes from IBKR.

The workflow is three stages: **find** the best spreads → **propose** the top pick
as an orderable spec (dry run, the default) → **execute** it as a native combo order
only when `--execute` is passed.

Supports cash-settled indices (**SPX, NDX, RUT, VIX, XSP, DJX**) — which trade as
`Index` contracts on their home exchange — as well as any optionable stock or ETF.

## Prerequisites

TWS or IB Gateway running locally with the API enabled:
- Paper trading: port 7497 (default)
- Live trading: port 7496

Index options require the appropriate **index-options market-data entitlement**
(separate from equity/ETF data). Without it, index quotes will not populate.

## Instructions

Optionally confirm a same-day (0DTE) expiry exists first:
```bash
uv run python scripts/zero_dte.py SYMBOL --expiries
```

Then find the best spreads (dry run — proposes only, places nothing):
```bash
uv run python scripts/zero_dte.py SYMBOL --type bear_call --budget 2000
```

Execute the chosen spread (places a live combo order):
```bash
uv run python scripts/zero_dte.py SYMBOL --type bear_call --budget 2000 \
    --account U1234567 --execute            # places the best pick
uv run python scripts/zero_dte.py SYMBOL --budget 2000 \
    --account U1234567 --execute --pick 2   # places the 2nd-ranked pick
```

## Arguments

- `SYMBOL` — underlying (e.g. `SPX`, `NDX`, `RUT`, `VIX`, `AAPL`, `SPY`)
- `--type` — `bear_call` (default, bearish/neutral), `bull_put` (bullish/neutral), or `iron_condor` (neutral)
- `--budget` — max capital at risk in dollars (default: 1000). Caps **total max loss**; position size is `floor(budget / max-loss-per-spread)`.
- `--account` — IBKR account the trade is committed to. Validated against the connection's managed accounts; echoed in the output. Defaults to the sole managed account when the login has exactly one. **Required with `--execute` when the login manages more than one account.**
- `--execute` — place the chosen spread as a live combo order. Without it (the default), the tool is a **dry run**: it proposes but places nothing.
- `--pick N` — 1-based rank of the candidate to execute (default: 1 = best).
- `--limit` — net credit limit price override (default: the candidate's net credit).
- `--replace` — if a live order for this symbol/expiry/type already rests, cancel and re-place it (default: refuse as a duplicate).
- `--expiry YYYYMMDD` — override the expiry (default: today ET, i.e. true 0DTE)
- `--top` — number of candidates to return (default: 5)
- `--min-pop` — minimum probability of profit, 0–1 (default: 0, no filter)
- `--max-width` — cap the strike width in dollars (optional)
- `--delta` — cap the `|delta|` of the short leg(s), e.g. `0.20` — a manual risk limit. Applies to both verticals and (both short legs of) iron condors. Uses the IBKR short-leg delta.
- `--allow-stale` — if IBKR streams no live quotes/greeks (off-hours), price legs from yesterday's settlement close and derive greeks via Black-Scholes. **Off by default:** greeks come only from IBKR, so a closed market returns no candidates (with a hint) rather than stale, model-computed ones.
- `--expiries` — list available expiries and whether today has a 0DTE
- `--port` — IB port (default: 7497 paper; use 7496 for live)

## Executing a trade

`--execute` places the chosen spread as a **single native BAG combo** — both legs (or
all four, for an iron condor) fill together, so IBKR margins it as one defined-risk
spread. The order is a **limit at the net credit** (`BUY` the combo at `-credit`, which
only fills at or better than that credit), time-in-force **DAY** (0DTE), tagged
`orderRef=ZDTE_<type>_<symbol>_<expiry>`, and routed to `--account`.

Guardrails before an order is sent:
- The account must resolve (explicit `--account`, or a sole managed account).
- `--pick` must be within the ranked list.
- The chosen spread's sized max loss must still fit `--budget`.
- **Duplicate guard** — if an active order with the same `orderRef`
  (`ZDTE_<type>_<symbol>_<expiry>`) already rests in the account, the placement is
  refused (reports the existing `order_id`). Pass `--replace` to cancel and re-place
  it instead. Prevents a second `--execute` from stacking a duplicate spread.

The connection is **read-only unless `--execute` is passed**, so a plain analysis run
can never place an order. Confirm the proposal with the user before executing.

## How ranking works

- **Probability of profit (POP)** — probability the spread finishes a winner: the
  underlying stays on the safe side of the short strike(s) at expiration. Taken from
  the IBKR short-leg delta (`POP ≈ 1 − |delta|`), with a Black-Scholes `N(d2)`
  fallback from IBKR implied vol when greeks are missing.
- **Expected value (EV)** — `POP × max_profit − (1 − POP) × max_loss`, in dollars for
  the full position after budget sizing.
- Candidates are ranked by **total EV**, ties broken toward higher POP.

## Output

JSON with:
- `underlying_price`, `expiry`, `dte`, `spread_type`, `budget`, `asset_type`, `account`
- `dry_run` — `true` unless `--execute` was passed
- `best` — the top-ranked spread
- `candidates` — top-N spreads, each with `legs` (action, right, strike, bid, ask,
  mid, delta, iv), `net_credit`, `width`, `pop`, `contracts`, per-contract and total
  `max_profit` / `max_loss`, `capital_at_risk`, `ev_total`, `breakeven`(s), `risk_reward`,
  `short_delta`, and `distance_to_short` / `distance_to_short_pct` (spot-to-short-strike
  cushion). Iron condors report `short_call_delta` / `short_put_delta` and
  `call_distance_to_short` / `put_distance_to_short`.
- `picked` — the 1-based rank executed (only when `--execute`)
- `order` — the placement result when `--execute`: `order_id`, `status`, `filled`,
  `remaining`, `quantity`, `limit_price` (negative = net credit), `account`, `order_ref`;
  or `{"ok": false, "error": ...}` if a guardrail blocked it

Present the top candidates as a table with columns: strikes, credit, POP,
short delta, distance-to-short (points and %), max profit, max loss, contracts, EV.
Lead with the `best` pick and state the direction and the price level it needs the
underlying to respect (the short strike / breakeven) — the distance-to-short is the
cushion before the trade starts losing.

## Data sourcing

- **Prices and greeks come from IBKR.** Leg prices are IBKR bid/ask/last; delta and IV
  are IBKR model greeks. The skill only does the spread arithmetic (mid, credit, width,
  max P&L, POP, EV, distances) on top of that data.
- By default, if IBKR streams no live quotes/greeks (market closed), the skill returns
  **no candidates** plus a `hint` — it will not compute greeks itself.
- `--allow-stale` opts into an off-hours fallback: price from yesterday's settlement
  `close` and derive IV/delta via Black-Scholes. Flagged as
  `data_delay: "stalled - using yesterday's close"`. Useful for previews only —
  those marks are stale, so numbers (especially far-OTM credits) aren't tradeable.

## Notes

- POP and EV are **model-implied** under standard (lognormal) assumptions — estimates
  of the odds, not guarantees.
- A credit spread's max loss is realized if price blows through the long wing; size
  accordingly. The budget caps that defined max loss, not slippage or gap risk.

## Timezone

All timestamps and time-based calculations use `America/New_York`. JSON output
includes `generated_at` (NY time string) and `data_delay`.

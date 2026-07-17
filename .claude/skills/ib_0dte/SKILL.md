---
name: ib_0dte
description: Find and place the best 0DTE (zero-days-to-expiration) credit spreads from Interactive Brokers. Default execution route is the EMA9/EMA21 + VIX<20 regime strategy (ema_vix_0dte.py), which auto-selects bull_put or bear_call based on today's 30-min bar signals and skips the trade when VIX >= 20. Supports cash-settled indices (SPX, NDX, RUT, VIX) and any optionable stock/ETF. Manual spread type override is available via zero_dte.py. Requires TWS or IB Gateway running locally.
dependencies: ["trading-skills"]
---

# IB 0DTE Credit Spread Finder & Executor

**Default execution route: `ema_vix_0dte.py`** — the EMA9/EMA21 + VIX<20 regime
strategy. It reads today's 30-min IB bars, checks VIX, and auto-selects `bull_put`
or `bear_call` (or skips entirely) before delegating to the spread finder. Use this
unless the user explicitly requests a manual spread type.

`zero_dte.py` is the manual override when the user specifies `--type bear_call`,
`--type bull_put`, or `--type iron_condor` directly.

Both scripts share the same spread-finding engine (find → propose → execute on
`--execute`) and all the same flags. All data comes from IBKR.

Supports cash-settled indices (**SPX, NDX, RUT, VIX, XSP, DJX**) — which trade as
`Index` contracts on their home exchange — as well as any optionable stock or ETF.

## Prerequisites

TWS or IB Gateway running locally with the API enabled:
- Paper trading: port 7497 (default)
- Live trading: port 7496

Index options require the appropriate **index-options market-data entitlement**
(separate from equity/ETF data). Without it, index quotes will not populate.

## Instructions

### EMA + VIX Strategy (recommended — fully automatic signal)

Run at **10:30 ET (14:30 UTC)**. The script checks VIX, reads today's 30-min bars,
determines bull_put vs bear_call from the EMA9/EMA21 cross + R→R confirmation,
then calls the spread finder automatically:

```bash
# Dry run (propose only, no order placed)
uv run python scripts/ema_vix_0dte.py NDX --budget 50000 --port 7496

# Live execution
uv run python scripts/ema_vix_0dte.py NDX --budget 50000 --port 7496 \
    --account U790497 --execute

# SPX variant
uv run python scripts/ema_vix_0dte.py SPX --budget 50000 --port 7496 \
    --account U790497 --execute
```

Signal logic (exits early with `success: false` and a reason if any check fails):
1. **VIX ≥ 20** → no trade (`signal: "VIX-SKIP"`)
2. **EMA9 last crossed above EMA21** → `bull_put`
3. **EMA9 last crossed below EMA21 + both 9:30 and 10:00 ET bars are red** → `bear_call`
4. **EMA down but R→R not confirmed** → no trade (`signal: "EMA-Dn-no-RR"`)

Additional flags:
- `--vix-threshold 20` — change the VIX cutoff (default: 20)
- `--target-delta 0.12` — short-leg delta target (default: 0.12, ≈1.5% OTM at VIX<20)
- All other `zero_dte.py` flags (`--max-width`, `--gex`, `--stop-mult`, etc.) pass through

### Manual spread finder (explicit type)

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
- `--limit` — absolute net-credit limit override. **Default: the candidate's `combo_ask_credit`** (the marketable BUY-side of the combo NBBO — `sum(short-leg bids) − sum(long-leg asks)`), which fills at market. Passing a higher credit here (e.g. mid) is likely to sit at the combo bid and not fill.
- `--limit-frac` — walk between the combo NBBO's marketable side and its mid: `combo_ask + frac × (net_credit − combo_ask)`. `0` = fully marketable (same as default), `0.5` = midpoint of combo NBBO, `1.0` = mid credit (rarely fills on multi-leg BAG combos). Computed at execution time, so it stays anchored to the fresh pull's combo quote. Ignored if `--limit` is set. (Note: IB **paper** often won't fill multi-leg 0DTE index combos at any marketable price — a paper-sim limitation, not a pricing issue.)
- `--replace` — if a live order for this symbol/expiry/type already rests, cancel and re-place it (default: refuse as a duplicate).
- `--stop-mult` — premium-cap stop: close when the spread reaches this multiple of the credit (default: `2.0` = lose ~1× credit). `0` disables the premium cap.
- `--stop-buffer` — points before the short strike to trigger the level stop (default: `0` = at the strike).
- `--stop-delta` — also stop when the short-leg delta reaches this level (optional, e.g. `0.30`).
- `--profit-target` — buy back after capturing this fraction of the credit, e.g. `0.5` = 50% (`0` disables). Default: per-symbol preset, else `0.50`.
- `--time-exit` — flatten remaining spreads at this ET time, e.g. `15:30` (`none` disables). Default: per-symbol preset, else `15:30`.
- `--fill-timeout` — seconds to wait for the entry to fill before cancelling it (default: `60`). The bracket needs a fill; if the entry doesn't fill it's cancelled so you're never unprotected.
- `--verify-stops` — check that every open 0DTE spread has a resting protective stop, then exit (no symbol required). Add `--repair` to place a strike-level stop on any unprotected position.
- `--repair` — with `--verify-stops`, auto-place a strike-level stop on unprotected positions.

Stop and exit defaults come from **per-symbol presets** (`STOP_PRESETS` in `zero_dte_stop.py`) — each maps `mult`, `buffer`, `delta`, `target` (profit-take), and `time_exit`. E.g. NDX uses `mult 3.0` + `0.30` delta backstop, `50%` target, `15:30` exit; SPX `mult 2.5`; unlisted symbols `mult 2.0`. Any explicit flag overrides the preset. Entry short-delta caps are separate (`ENTRY_MAX_DELTA`: 0.12 index / 0.20 stock). These are starting points; tune them with live data.
- `--expiry YYYYMMDD` — override the expiry (default: today ET, i.e. true 0DTE)
- `--top` — number of candidates to return (default: 5)
- `--min-pop` — minimum probability of profit, 0–1 (default: 0, no filter)
- `--max-width` — cap the strike width in dollars (optional)
- `--delta` — cap the `|delta|` of the short leg(s) at entry. Applies to both verticals and (both short legs of) iron condors. **Defaults by class: 0.12 for indexes, 0.20 for stocks** (`ENTRY_MAX_DELTA` in `zero_dte.py`); pass a value here to override. The effective cap is echoed as `max_short_delta` in the output.
- `--gex` — compute the **dealer gamma-exposure profile** (net GEX, gamma flip, call/put walls), annotate each candidate against the walls, and gate `entry_quality` on the regime. See **Gamma exposure (GEX)** below. Costs an extra chain fetch (it pulls both option sides).
- `--gex-weight` — size measure behind each strike: `volume` (today's prints), `oi` (prior settlement's open interest), or `auto` (default: volume once it has printed, else OI).
- `--allow-stale` — if IBKR streams no live quotes/greeks (off-hours), price legs from yesterday's settlement close and derive greeks via Black-Scholes. **Off by default:** greeks come only from IBKR, so a closed market returns no candidates (with a hint) rather than stale, model-computed ones.
- `--no-events` — skip the live economic-calendar lookup (falls back to static event guidance). The calendar is fetched by default and needs no API key.
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

## Exit bracket (automatic, non-negotiable on `--execute`)

Every `--execute` **atomically attaches a full OCA exit bracket** — you can never end
up holding an unmanaged 0DTE position:

1. The entry combo is placed and the tool **waits for it to fill** (`--fill-timeout`).
2. If it doesn't fill, the entry is **cancelled** (no position, no risk) and the result
   reports why — retry with a marketable `--limit` or during liquid hours.
3. On fill, three closing orders are placed in **one OCA group** (whichever fills first
   cancels the others, server-side):
   - **Profit target** — a resting limit to buy back at `(1 − target) × credit`.
   - **Stop** — a conditional order that buys back when the **underlying** breaches the
     stop level.
   - **Time exit** — a conditional order that flattens at the `--time-exit` ET time.
   If bracket placement fails, the position is **emergency market-closed** immediately.

The profit target naturally captures near-worthless winners well before the timer, so
the time exit mainly flattens positions still hovering near breakeven into the close.

The stop trigger is **level-anchored on the underlying** (robust to option-price noise),
taking whichever of these fires first:
- **Short strike** (± `--stop-buffer`) — the "thesis broken" level.
- **Premium cap** (`--stop-mult`) — the underlying level where the loss reaches
  `mult × credit`, computed via Black-Scholes at entry.
- **Short delta** (`--stop-delta`, optional).

Bear call → stops if the index rises; bull put → if it falls; **iron condor → two
OCA-linked stops** (either breach closes the whole condor). The close is a **marketable
limit capped at the spread width** — fills at market but never worse than the defined
max loss. A stop reduces the *average* loss; it does **not** guarantee the price in a
gap, so the budget-capped max loss remains the true floor.

### Verifying / repairing stops

```bash
uv run python scripts/zero_dte.py --verify-stops --account U1234567          # report
uv run python scripts/zero_dte.py --verify-stops --repair --account U1234567 # auto-fix
```

Scans open **0DTE** option positions per account and buckets them into `protected`
(a resting `ZDTE_STOP_…` order exists), `unprotected`, and `unrecognized` (legs that
don't form a recognized spread). With `--repair`, each unprotected recognized spread
gets a **strike-level** stop (± the symbol's preset buffer) — a safety net that needs
no live market data. Run it after entering trades, and periodically, to confirm nothing
is naked.

## How ranking works

- **Probability of profit (POP)** — probability the spread finishes a winner: the
  underlying stays on the safe side of the short strike(s) at expiration. From the
  IBKR short-leg delta (`POP ≈ 1 − |delta|`), BS `N(d2)` fallback.
- **Expected value (EV)** — the **expected P&L integrated over a lognormal** with
  realized vol = `--rv-ratio × implied` (default 0.85). This counts *partial* losses
  (breach just past the short is a small loss), not a flat max loss — which fixes the
  far-OTM bias of the old binary `POP×maxP − (1−POP)×maxL`. `ev_model` is echoed
  (`expected_pnl_rv0.85`); if a leg has no IV it falls back to the binary formula.
  - Lower `--rv-ratio` = more credit-hungry (favors richer near-the-cap strikes);
    `1.0` ≈ fair (EV near zero — don't use). It's an assumption, not a guarantee.
- **`--target-delta`** — pin the short leg(s) to a delta (± 0.05) for direct strike
  control, e.g. `--target-delta 0.15`. Still bounded by `--delta`.
- Candidates are ranked by **total EV**, ties broken toward higher POP.

## Output

**Every run is automatically saved** to `sandbox/` as timestamped JSON (e.g.
`NDX_0dte_bear_call_exec_2026-07-10_093015.json`), and the path is echoed as
`saved_to`. This gives a durable trade log — including the `order.bracket` /
`binding` details that TWS alone doesn't reconstruct. No flag needed.

JSON with:
- `underlying_price`, `expiry`, `dte`, `spread_type`, `budget`, `asset_type`, `account`
- `dry_run` — `true` unless `--execute` was passed
- `timing` — built-in intraday guidance (see **Timing & event guidance** below)
- `gex` — dealer gamma-exposure profile when `--gex` is passed, else `null` (see
  **Gamma exposure (GEX)** below): `regime`, `net_gex_bn`, `flip_level`, `call_wall`,
  `put_wall`, `heaviest_strikes`, `weight_source`, `coverage`, `caveats`, and a
  `guidance` sub-block
- `best` — the top-ranked spread
- `candidates` — top-N spreads, each with `legs` (action, right, strike, bid, ask,
  mid, delta, iv), `net_credit` (mid credit, used for max_profit/EV/breakevens),
  `combo_ask_credit` (marketable BUY-side of the combo NBBO — the default execution
  limit; what fills at market), `combo_bid_credit` (resting BUY bid — best possible
  credit, rarely fillable), `width`, `pop`, `contracts`, per-contract and total
  `max_profit` / `max_loss`, `capital_at_risk`, `ev_total`, `breakeven`(s), `risk_reward`,
  `short_delta`, and `distance_to_short` / `distance_to_short_pct` (spot-to-short-strike
  cushion). Iron condors report `short_call_delta` / `short_put_delta` and
  `call_distance_to_short` / `put_distance_to_short`.
- `picked` — the 1-based rank executed (only when `--execute`)
- `order` — the placement result when `--execute`: `order_id`, `status`, `filled`,
  `remaining`, `quantity`, `limit_price` (negative = net credit), `account`, `order_ref`,
  `entry_status`, `log` (IB's status/error messages for this order — surfaces the reject
  reason when an entry goes terminal-Cancelled without filling), and `bracket` (the
  attached OCA exit bracket: `profit_target` (`limit_debit`), `stops` (each side's
  `trigger` / `binding` level / `order_id`), and `time_exit` (`cutoff`); or
  `{"ok": false, ...}` with an `emergency_close` if bracket placement failed); or
  `{"ok": false, "error": ...}` if a guardrail blocked it

Present the top candidates as a table with columns: strikes, credit, POP,
short delta, distance-to-short (points and %), max profit, max loss, contracts, EV.
Lead with the `best` pick and state the direction and the price level it needs the
underlying to respect (the short strike / breakeven) — the distance-to-short is the
cushion before the trade starts losing.

## Paper-test report

Aggregate your saved runs into a summary:
```bash
uv run python scripts/report.py            # text summary
uv run python scripts/report.py --json     # machine-readable
```

- **Entries** (from `sandbox/*_exec_*.json`, automatic): trades placed by symbol/type,
  entry short-delta range, avg POP, capital at risk, and the **stop level placed**
  (binding) distribution.
- **Outcomes** (from the latest `ib_0dte_paper_test_log_*.md` you fill in): win rate,
  avg win/loss, **expectancy per trade**, **max drawdown**, and the **actual closed-by**
  leg distribution. Realized P&L only exists once a trade resolves, so it comes from the
  daily log's `P&L` / `Closed by` columns — the entry JSON only captures placement.

Watch **expectancy**, not win rate: a high win rate with one fat loss can still be
negative (the report makes that obvious).

## Gamma exposure (GEX)

`--gex` adds a `gex` block estimating how much gamma market makers hold across the
chain, and what their hedging of it does to the tape:

```bash
uv run python scripts/zero_dte.py SPX --type bear_call --budget 2000 --gex
```

Per strike, `GEX = gamma × size × 100 × spot² × 0.01` — the dollars of dealer delta
that must be re-hedged per 1% move. Net GEX is **calls minus puts**, on the standard
assumption that dealers are **long call gamma / short put gamma** (customers buy puts
and sell calls).

- **`regime`** — `positive_gamma`: dealers hedge *against* the move (sell rallies, buy
  dips), so vol is suppressed and price mean-reverts — the supportive regime for short
  premium. `negative_gamma`: they hedge *with* the move, amplifying it — the regime that
  runs credit spreads over. `neutral_gamma`: the book is balanced, no edge either way.
- **`flip_level`** — the spot where net GEX crosses zero, found by re-deriving every
  strike's gamma across a ±5% spot grid. Above it you're in the suppressive regime,
  below it the amplifying one. `guidance.spot_vs_flip` says which side you're on.
- **`call_wall` / `put_wall`** — the heaviest gamma strikes above and below spot. Dealer
  hedging tends to defend them, so they act as barriers.
- **`guidance.strike_guidance`** — where to put the short leg: at or **beyond** the wall
  (bear call ≥ call wall, bull put ≤ put wall), so the level dealers defend stands
  between spot and your short strike.
- Each candidate gets a **`gex`** tag (`beyond_wall` / `at_wall` / `inside_wall` per
  short leg, with `distance_to_wall`) and a **`gex_ok`** boolean. `inside_wall` means
  price can reach your short strike without ever contesting the wall.
- **The regime gate**: a `negative_gamma` read **downgrades `timing.entry_quality` one
  notch** (best/good → fair → avoid) and records `timing.gex_gate` with the original
  value and the reason. The clock only knows the time of day; the regime knows whether
  today's hedging damps moves or feeds them.

GEX is **advisory only** — it never changes strike selection, sizing, or the order path.
Surface `gex.regime`, the walls, and any `guidance.warnings` alongside the timing block.

**Weighting caveat (read this).** IBKR's open interest is the **prior settlement's** — on
a 0DTE expiry most of the book is opened the same morning, so OI misses the flow that
actually drives today's hedging. `auto` therefore weights by **same-day volume**, which
sees today's flow but double-counts round-trips and can't tell an opening trade from a
closing one. `weight_source` and `caveats` in the output state which was used. A GEX
number built on the wrong measure can point at the wrong wall entirely — treat it as a
regime filter and a strike-placement prior, not as an edge to lean on hard. The
dealer long-call/short-put assumption itself fails when customers are the ones buying
calls (a squeeze), which inverts the profile.

## Timing & event guidance

Every run includes a `timing` block, computed from the current ET clock:

- `window` — `pre_market` / `opening_bell` / `morning_prime` / `midday` / `afternoon` /
  `power_hour` / `after_hours` / `weekend`
- `entry_quality` — `best` / `good` / `fair` / `avoid` / `closed`, tailored to the
  spread type (credit spreads favor mid-morning; iron condors favor the midday lull;
  the open and the final power hour are `avoid`)
- `recommendation` — one-line plain-English guidance for the current window
- `events` — event-risk guidance, with `source`:
  - `source: "nasdaq"` (**live economic calendar**, keyless, via Nasdaq): reports
    `events_today` (each with `event`, `time_et`, `impact`, `actual`/`consensus`/`previous`),
    `high_impact_today` (FOMC/CPI/PPI/NFP/PCE/GDP/retail/ISM + Fed-chair remarks), and
    `warnings` for high-impact and imminent (within ~30 min) releases.
  - `source: "static"` (fallback when the calendar can't be reached, or `--no-events`):
    recurring intraday-window warnings plus a `verify_before_trading` checklist.
- Timing is holiday/early-close aware via the NYSE calendar (half-days shift the close
  and power-hour windows).

**Surface this prominently.** Before proposing or (especially) executing, state the
`timing.recommendation` and any `timing.events.warnings`; if `entry_quality` is `avoid`
or `closed`, call that out and suggest waiting. Lead with any high-impact event today
(e.g. "FOMC at 14:00 ET") — it can gap the index straight through the short strikes.

The live calendar is fetched by default (no API key needed); pass `--no-events` to skip
it. Event data is US macro releases; for stock underlyings also confirm earnings.

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

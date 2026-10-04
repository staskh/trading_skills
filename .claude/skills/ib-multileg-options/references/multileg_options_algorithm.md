# Multi-Leg Options Playbook: Rules as an Algorithm

Built from the NavigationTrading course PDFs: *Iron Duck* (slides, cheat sheet, watch list), *Dynamic Butterflies* sessions 1 and 2, and *Time Fly*.
It's meant as a rules spec that trading agents can implement.

> **Where each rule comes from.** Rules tagged **[C]** are taken directly from the PDFs. Rules tagged **[A]** are my additions. The course leaves those points to the trader's judgement, and an automated system needs a concrete value. Check every [A] value before you rely on it.
> This is not financial advice. It's a write-up of educational material. Backtest it and paper-trade it before using real money.

---

## 1. Pipeline

```
every scan (at end of day, plus once intraday):
    for symbol in universe:
        if not passes_liquidity(symbol): continue
        regime = classify(symbol)               # direction × IV level × IV trend
        candidates = select_strategies(regime)
        for strat in candidates:
            legs = build_legs(strat, chain)     # strikes picked by delta
            if validate(strat, legs) and risk_ok(strat, legs):
                submit_limit_order(legs)        # mid-price, then walk toward the natural price
    for position in open_positions:
        manage(position)                        # profit target / stop / time exit / adjustment
```

---

## 2. Universe and liquidity filter

| Rule | Source |
|---|---|
| Preferred: SPX, RUT, NDX (European style, cash settled, Section 1256 tax treatment, no assignment risk). ETF alternatives: SPY, QQQ, IWM, DIA | [C] |
| Stocks: price > $200, or > $100 when trading an earnings event. Watch list: AAPL ADBE BA BIIB BKNG CMG COST GOOG GS AMZN HD LMT MA MCD NFLX SHOP TSLA ULTA UNH ROKU | [C] |
| Futures (Iron Duck): /ES /NQ /ZB /ZN /CL /NG /GC /6E /6B /ZS /ZW /ZC | [C] |
| Open interest per leg in the 100s or higher; tight bid/ask | [C] |
| Spread threshold: bid/ask ≤ 5% of mid on each leg, and ≤ 10% for the whole combo | [A] |
| Small accounts: use cheaper underlyings (DIA, SPY, $200–300 stocks), hold 1–2 positions, trade 1–2 contracts | [C] |

---

## 3. Regime classification

The course says to pick strikes "based on current market assumptions". It doesn't define a direction signal or an IV threshold, so the values below are **[A]** unless tagged otherwise.

**Direction** (pick one signal and keep it consistent):
- `BULL`: close above the 20-day EMA, the 20 EMA above the 50 EMA, and the 20 EMA slope positive.
- `BEAR`: the mirror of `BULL`.
- `NEUTRAL`: everything else, or price inside a ±1 ATR band around the 20 EMA.
- You can also override this manually, or feed it from the existing `scanner-bullish` / `news-sentiment` skills.

**IV level** (IV Rank over 52 weeks, using the symbol's IV or its volatility index such as VIX or RVX):
- `HIGH`: IVR ≥ 50. `MID`: 25 to 50. `LOW`: below 25.

**IV trend today** (this matters for butterflies **[C]**):
- `EXPANDING`: today's IV (or VIX) is above yesterday's close.
- `FLAT`: within ±2%.
- `CONTRACTING`: below yesterday's close.

**Skew flag**: `CALL_RICH` when the 25-delta call IV is above the 25-delta put IV. This is common in commodities like /GC, /CL and /NG, and is what triggers the Reverse Iron Duck **[C]**.

**Event flag**: `EARNINGS` when an earnings date falls before the candidate expiration.

---

## 4. Strategy selection matrix

| Direction ↓ / IV → | HIGH IV | MID IV | LOW IV |
|---|---|---|---|
| **NEUTRAL** | Iron Duck, Flat Head Woodpecker | Delta-Neutral Fly, Flat Head Woodpecker, Time Fly | Delta-Neutral Fly (only if IV is expanding) |
| **BULL** | Iron Duck (no upside risk, makes money on a rally) | Bullish Call Fly (30Δ), Bullish BWB | Bullish Call Fly |
| **BEAR** | Big Beak Woodpecker, Bearish Put Fly | Bearish Put Fly (30Δ), Small Beak Woodpecker, Time Fly | Bearish Put Fly |
| **CALL_RICH skew** | Reverse Iron Duck | Reverse Iron Duck | (skip) |
| **EARNINGS** | Iron Duck in the nearest weekly or monthly expiration (< 21 DTE), stock > $100 | | |

Gates applied on top of the matrix:
- **Any butterfly-family trade** (Delta-Neutral, Directional, BWB, Woodpeckers, Time Fly) is entered only when the IV trend is `FLAT` or `EXPANDING`. Skip it if IV is contracting **[C]**.
- **Iron Duck**: entry is better when IV is high, "but if the setup works, then trade it". In practice the validation constraints in §5.1 are the real gate, and low IV usually fails the credit and POP checks on its own **[C]**.
- **Portfolio delta** **[C]**: Iron Ducks are the tool for keeping a short-delta hedge without upside risk. If portfolio beta-weighted delta is too long, Iron Ducks get priority.

The matrix itself is **[A]**: it's my mapping of each strategy's described use onto a grid.

---

## 5. Strategy specifications

Delta conventions: put deltas are written as absolute values. Strikes snap to the nearest listed strike. **All deltas are approximate. Search the nearby strikes until the validation rules pass [C].**

### 5.1 Iron Duck (Broken-Skewed Iron Condor): credit, no upside risk [C]

| Item | Rule |
|---|---|
| Legs | **Sell** call at ~65Δ (in the money) · **Buy** call 1 strike higher · **Sell** put at ~15Δ · **Buy** put at ~10Δ |
| DTE | Index: 1–21. Futures: 7–21. Earnings: nearest weekly, or nearest monthly under 21 DTE. **Ladder** entries across expirations and price levels; the order of entries matters |
| Validate (all must pass) | POP > 85% · upside P/L at expiration ≥ 0 (call-spread width ≤ total credit) · theoretical loss at the downside break-even ≤ total credit · credit ≥ $1.00 for equity options |
| Strike search | Start from the target deltas. If a check fails, move the short put further out of the money (raises POP), widen the put wing, or move the call pair. Stop after N tries **[A]** |
| Exit | Close **manually** (no resting stop order) when the loss reaches **100% of credit**, with an alert at the break-even. Otherwise hold to expiration or let it expire. Equities and futures: close on expiration day if a short leg is in the money and its long partner isn't, to avoid assignment |
| Adjustments | **None, and no rolls** |
| Risk | All Iron Ducks combined < 30% of account. Size for max loss, because a gap can blow straight through the stop |

**Variants.** Strike layouts are read from the slide risk-graph screenshots **[C]**. The delta targets are my approximations of those strikes **[A]**.
- **Reverse Iron Duck** (CALL_RICH): the mirror image, with **no downside risk**. Sell a ~65Δ put (in the money), buy the put **1 strike lower**, sell a ~15Δ call, buy a ~10Δ call. Require total credit ≥ put-spread width. Slide example on /GC with futures near 1480–1490: sell 1490P, buy 1485P, sell 1555C, buy 1580C, for a 5.50 credit on a 5-wide put spread. The other validation rules and exits are the same as the Iron Duck.
- **Broken-Wing Iron Butterfly**: sell a call and a put **at the same strike**, at or just below spot (short call about 55–60Δ, slightly in the money). Buy a **narrow call wing**, sized so total credit ≥ call width (no upside risk). Buy a **wide put wing**, about 2.5× the call width (around 10–15Δ). Slide example on SPY near 288: sell 286C and 286P, buy 291C, buy 273P, for a 5.48 credit on a 5-wide call wing. It has a higher max profit and a lower POP (~80%) than the Iron Duck. Exit with a **stop at 50% of credit** **[C]**, or hold to expiration. No adjustments.
- **Jade Lizard** (the "naked" Iron Duck): the Iron Duck **without the long put**. Sell a ~65Δ call, buy the call 1 strike higher, sell a ~15Δ put, and require credit > call width. Slide example on SPX: sell 2800C, buy 2815C, sell 2640P, for a 22.50 credit on a 15-wide call spread. The slide's warnings: **undefined risk**, buying power about 30× higher, and a theoretical loss at break-even of more than 2× the credit **[C]**. This fails the Iron Duck's "loss at break-even ≤ credit" rule, so keep it **disabled by default**.

### 5.2 Delta-Neutral Butterfly: debit [C]

| Item | Rule |
|---|---|
| Legs | Short 2× ATM, about 50Δ. Long wings an **equal** number of strikes either side. All calls or all puts **[C]** |
| Wing by delta **[A]** | Upper long at the strike nearest **25Δ call**. Lower long the **same number of strikes below** the short strike (about 25Δ put); the equal distance takes priority over the delta. This works out to roughly one expected move per wing |
| DTE | Any cycle **[C]**. Default 7–21 **[A]** |
| Width sanity check **[A]** | Wing width within 0.75–1.5× the ATM straddle price. For SPX, the Time Fly guidance of 30–60 points (wider for longer DTE) is a cross-check |
| Entry | IV flat or expanding |
| Exit | Profit target **20–30% of debit** · stop when loss > **75% of debit** · exit by **1 DTE** |

### 5.3 Directional Butterfly: debit [C]

- **Bullish**: all calls, short strikes near the **30Δ call**, equal wings **[C]**.
  - Wings by delta **[A]**: inner (lower) long at about **45Δ call**, outer (upper) long the same number of strikes above (lands around 15–18Δ).
- **Bearish**: all puts, short strikes near the **30Δ put**, equal wings **[C]**.
  - Wings by delta **[A]**: inner (upper) long at about **45Δ put**, outer (lower) long the same number of strikes below.
- DTE and exits are the same as §5.2.

### 5.4 Broken-Wing Butterfly (BWB)

- Short strikes out of the money (calls for bullish, puts for bearish). Wings an **unequal** distance from the shorts **[C]**.
- Time Fly guidance for SPX: main width 30–60 points, with the broken side 5–20 points wider. A longer DTE means wider spreads **[C]**.

Delta layouts **[A]**. "Near" wing = the long between the shorts and spot. "Far" wing = the long on the other side.

| Variant | Type | Short 2× | Near long | Far long | Price condition |
|---|---|---|---|---|---|
| Bullish BWB | Calls | 30Δ | ~45Δ | 1.5–2× the near-wing distance (~10Δ) | Small credit, or debit ≤ 10% of near-wing width |
| Bearish BWB | Puts | 30Δ | ~45Δ | 1.5–2× the near-wing distance (~10Δ) | Same |
| Neutral BWB | Puts | 50Δ | 1 width above | 1.5–2 widths below | Small credit or small debit |

- The wider (far) wing is the side carrying the risk, so a bullish BWB loses on a sharp rally through it and a bearish BWB loses on a sharp drop.
- Exits aren't stated for a plain BWB **[A]**: use the §5.2 rules (profit target 20–30% of max profit, stop when loss > 75% of max risk, exit at 1 DTE).

### 5.4a Strikes-by-delta summary (all non-Iron-Duck strategies)

| Strategy | Type | Long | Short | Long | Notes |
|---|---|---|---|---|---|
| Delta-neutral fly | C or P | 25Δ wing **[A]** | 2× 50Δ **[C]** | equal distance **[C]** | |
| Bullish fly | Calls | 45Δ **[A]** | 2× 30Δ **[C]** | equal distance (~15–18Δ) | |
| Bearish fly | Puts | 45Δ **[A]** | 2× 30Δ **[C]** | equal distance (~15–18Δ) | |
| Bullish / bearish BWB | C / P | 45Δ **[A]** | 2× 30Δ **[A]** | 1.5–2× distance (~10Δ) **[A]** | |
| Neutral BWB | Puts | 1 width above **[A]** | 2× 50Δ **[A]** | 1.5–2 widths below **[A]** | |
| Big Beak | Puts | 50Δ | 2× 42Δ | 30Δ | all **[C]**; POP 65–75% |
| Small Beak | Puts | 48Δ | 2× 40Δ | 30Δ | all **[C]**; POP 55–65% |
| Flat Head | Puts | 50Δ | 43Δ + 28Δ | 20Δ | all **[C]**; POP 70–80% |
| Time Fly put fly | Puts | upper long above spot **[C]** | 2× ~30Δ **[C]** | 30–60 pts wide (SPX) **[C]** | Upper long ≈ 50–55Δ **[A]** |
| Time Fly calendar | Calls | back month +1–7 DTE | front ~40Δ **[C]** | — | same strike = calendar; higher back strike = diagonal |
| Fly add-on adjustment | C (up) / P (down) | equal wing | 2× ~30Δ **[C]** | equal wing | |
| Reverse Iron Duck | P + C | put 1 strike lower | 65Δ put + 15Δ call | 10Δ call | from the slide example |
| BW Iron Butterfly | C + P | call: credit ≥ width | ~58Δ C + P, same strike | put ~10–15Δ | from the slide example |
| Jade Lizard | C + P | call 1 strike higher | 65Δ C + 15Δ P | (none) | disabled |

Strike-search order **[A]**: (1) place the short strikes at their target delta, (2) place the wings by the delta or distance rule, (3) run validation, (4) if it fails, move each wing ±1 strike, then the shorts ±1 strike, for at most 6 tries, then skip the symbol.

### 5.5 Woodpeckers: put-based unbalanced flies and condors [C]

All three use **puts** and **any expiration cycle**. Deltas vary by symbol, duration and IV level.

| Strategy | Legs (put Δ) | Pricing condition | Target POP |
|---|---|---|---|
| **Big Beak** | +1 @30 · −2 @42 · +1 @50 | "Beak profit" > theoretical loss near the downside break-even | 65–75% |
| **Small Beak** | +1 @30 · −2 @40 · +1 @48 | Small credit or small debit | 55–65% |
| **Flat Head** | +1 @20 · −1 @28 · −1 @43 · +1 @50 | Small credit or small debit | 70–80% |

**Exit (all three):** exit when price trades near the **downside break-even** · start **scaling out at 20% profit** (**[A]**: close ⅓ at 20%, ⅓ at 30%, the rest at 40% or 1 DTE) · exit at **1 DTE**.

### 5.6 Time Fly: put fly plus call calendar [C]

**Preferred method:**
1. **Entry:** buy a put fly with short legs at ~30Δ, the upper long **above** the current price, and width 30–60 points for SPX. Balanced or broken wing. 7–21 DTE (minimum 3). Enter on a day when **IV is expanding**, positioning price "under the tent".
2. If price **moves lower** into the tent, exit at the profit target.
3. If price **rises above the upper long**, add a **~40Δ call calendar or diagonal**. Its short leg goes in the same cycle as the fly, and the back month is 1–7 DTE later. Adjust at **end of day**. Add at most **2× calendars** in total.

- **Exit:** profit target **5–10%+ of max risk** (the example uses 15–20% of debit) · exit near the downside break-even · exit near 1 DTE · **consider closing if the loss exceeds 15%**.
- **PDT:** some positions close the same day they open, so the account needs more than $25k.

### 5.7 Butterfly adjustments (session 2) [C]

These apply to the §5.2–5.5 flies. Iron Ducks are never adjusted.

| Trigger | Action | Effect |
|---|---|---|
| Price moves **up** with a low chance of returning to the peak-profit zone | **A:** sell a short put vertical below, **or** **B:** roll all strikes up | Cuts or removes upside risk, raises theta. A uses more capital; B locks in some profit |
| Price leaves the profit range **up or down** | Add another fly in the direction of the move, with short strikes near **30Δ** (calls when price moved up, puts when it moved down) | Widens the profit range, raises theta and risk |

**[A]** "Low probability of returning" means price is more than 1 wing-width from the short strike with ≤ 40% of DTE remaining. Limit to 1 add-on fly per position.

---

## 6. Risk and position sizing

| Rule | Source |
|---|---|
| Butterfly family: max **5% of account per position**, **30% total allocation** | [C] |
| Iron Ducks: **< 30% of account** in total | [C] |
| Ladder: several smaller positions across expirations and strikes beats one large one | [C] |
| Probability of touching a strike ≈ **2 × delta** (or 2 × (1 − POP)). Use it to set alert levels | [C] |
| Global cap on all strategies combined: 50% of net liquidation value; ≤ 3 open positions per underlying per expiration | [A] |
| Kill switch: stop opening new trades for the rest of the day if VIX gaps more than +20% intraday, or if daily P/L falls below −2% of the account | [A] |

---

## 7. Execution rules for agents [A]

- Send each multi-leg trade as **one combo order** (never leg in). Price it at the mid, then move toward the natural price in small steps every 30–60 seconds, and give up after 5 tries.
- Stops are **soft**. Following the course, there are no resting stop orders: the agent checks the combo mark against its stop on each poll.
- Recheck the Greeks and POP right before submitting. Abort if the order would fill outside the validated range.
- Run scans once around 10:00 ET and once in the last hour. Make Time Fly and butterfly adjustments at end of day.
- Equities: on expiration day, close any position with a short leg near the money (assignment risk). Index options settle to cash.
- Log every decision with the regime, candidates, chosen legs, validation results and fill, so the rules can be backtested and tuned later.

---

## 8. Config

All parameters, including every strike-by-delta rule above, live in [`multileg_options_config.yaml`](multileg_options_config.yaml). Agents should read their values from that file rather than hard-coding them. Keep it in sync with this document.

---

## 9. Gaps to resolve before automating

1. **Direction signal** isn't defined in the course. The EMA rule in §3 is a placeholder.
2. **IV indicator**: the course uses its own "NavigationTrading IV indicator", whose settings aren't in these PDFs. IV Rank is a stand-in.
3. **Wing placement** for the flies in §5.2–5.4 isn't given by delta in the course. The wing deltas in §5.4a are proposals to backtest.
4. **Variant layouts** for the Reverse Iron Duck, Broken-Wing Iron Butterfly and Jade Lizard come from single slide screenshots. The delta targets are approximations of those example strikes.
5. **Backtests** in the deck are SPX Iron Ducks at 5/7/10/14/21 DTE, plus 2007–09. Results were screenshots only. Re-run them yourself before trusting any of the probabilities.

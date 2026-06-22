# PMCC Advisor Report - Markdown Template

Format the JSON data into a markdown report saved to `sandbox/`.

**Filename**: `pmcc_advisor_{ACCOUNT}_{YYYY-MM-DD}_{HHmm}.md`
- Use first account ID for `ACCOUNT`. If multiple accounts, use "multi".
- Derive date/time from `generated_at`.

---

## Report Sections

### 1. Header

```markdown
# PMCC Advisor Report
**Generated:** {generated_at}  |  **Data:** {data_delay}  |  **Account:** {accounts joined by ", "}
**Price mode:** {price_mode}  |  **Min roll DTE:** {min_roll_dte}
**Scope:** Full portfolio   ← use this line when symbols_filter is null
**Scope:** Filtered — {symbols_filter joined by ", "}   ← use this line when symbols_filter is non-null
```

---

### 2. Red Flags Summary

Only include this section if any spread triggers at least one condition. Title: `## ⚠️ Red Flags`

List each flagged spread as a bullet. Check all of the following:

| Condition | Threshold | Flag text |
|-----------|-----------|-----------|
| Assignment probability | > 40% | `HIGH ASSIGN RISK — {assign_prob}% probability` |
| DTE on short leg | < 7 days | `EXPIRING SOON — {dte:.1f} days` |
| No roll candidates | empty list | `NO VIABLE ROLLS` |
| Earnings within short window | `warning_short == true` | `EARNINGS ⚠️ {earnings.date} {earnings.timing} — within current short window` |
| Earnings in roll windows | `warning_roll_indices` non-empty | `EARNINGS ⚠️ {earnings.date} {earnings.timing} — overlaps roll(s) {warning_roll_indices}` |

Format each line as:
```
- **{SYMBOL}**: {flag1}, {flag2}, ...
```

Multiple flags for the same symbol are combined on one line, comma-separated.

---

### 3. One Section Per Spread

For each entry in `spreads[]`, render a full section. Order: by assignment probability descending (most at-risk first).

#### Section header

```markdown
---

## {SYMBOL} — {qty} contract(s) | Spot: ${underlying_price} | LEAPS: {long.expiry formatted as "Mon DD YYYY"}
```

#### 3a. Company Description

Always include a one-sentence description of what the company does, drawn from your own knowledge.

```markdown
> {Company name} — {one sentence: sector, primary business, why it's relevant to a trader}
```

Example: `> JPMorgan Chase (JPM) — largest U.S. bank by assets, operating across investment banking, consumer finance, and asset management.`

#### 3b. Technical Profile (include only if technical data is present in conversation context)

If the conversation context contains bullish scan results, technical analysis, or any RSI / MACD / EMA / ADX data for this symbol, render this section. If no technical data is available, omit the section entirely — do not invent values.

```markdown
### Technical Profile

| Indicator | Value | Signal |
|-----------|-------|--------|
| Price vs SMA20 | {pct_from_sma20:+.1f}% | Above / Below |
| Price vs SMA50 | {pct_from_sma50:+.1f}% | Above / Below |
| RSI (14) | {rsi:.1f} | Bullish (>50) / Neutral / Oversold (<30) |
| MACD | {macd:.3f} vs signal {macd_signal:.3f} | Bullish / Bearish crossover |
| EMA9 / EMA21 | {ema9:.2f} / {ema21:.2f} | Golden cross {N}d ago / Death cross / Flat |
| ADX | {adx:.1f} | Strong trend (>25) / Weak |
| 3mo Return | {period_return_pct:+.1f}% | — |
| Bullish Score | {score:.2f} / 9.5 | — |
```

Only include rows for which data is available. Omit rows where the value is unknown.

Crossover interpretation:
- EMA golden cross ≤5d ago: "Fresh golden cross {N}d ago"
- EMA golden cross 6–10d ago: "Golden cross {N}d ago"
- EMA golden cross >10d ago: "Golden cross {N}d ago (aging)"
- MACD crossover ≤3d ago: "Fresh bullish crossover {N}d ago"
- No crossover in period: omit the crossover detail

#### 3c. Earnings Alert (only if `earnings.date` is not null)

```markdown
> **Earnings:** {earnings.date} {earnings.timing or ""}
```

If `warning_short` is true, append: ` — ⚠️ within current short window`
If `warning_roll_indices` is non-empty, append: ` — ⚠️ overlaps roll(s) {warning_roll_indices}`

#### 3d. Spread Structure

Two-row table showing both legs side by side:

```markdown
### Spread Structure

| Leg | Strike | Expiry | DTE | Avg Cost | Current Price | IV (BS) | IV (IB) |
|-----|--------|--------|-----|----------|---------------|---------|---------|
| Long (LEAPS) | ${long.strike} | {long.expiry → Mon DD YYYY} | {long.dte:.0f}d | ${long.avg_cost:.2f} | ${long.current_price or "—"} | {long.iv_pct or "—"}% | {long.ib_iv_pct or "—"}% |
| Short | ${short.strike} | {short.expiry → Mon DD YYYY} | {short.dte:.1f}d | received ${short.premium_received:.2f} | ${short.current_price or "—"} | {short.iv_pct or "—"}% | {short.ib_iv_pct or "—"}% |
```

Show IB delta and IB IV columns only if `ib_delta` or `ib_iv_pct` are non-null for any row; otherwise omit them.

#### 3e. Short Leg Risk

```markdown
### Short Leg Risk

| Delta (BS) | Delta (IB) | Assignment Prob | DTE |
|------------|------------|-----------------|-----|
| {short.delta} | {short.ib_delta or "—"} | **{short.assignment_prob_pct}%** | {short.dte:.1f}d |
```

Color cue for assignment probability (text label only, no emojis unless instructed):
- < 20%: LOW
- 20–35%: MODERATE
- 35–50%: HIGH ⚠️
- > 50%: VERY HIGH 🚨

Append the color cue in parentheses after the probability value in the table cell.

#### 3f. Daily P&L Projections

Show all rows from `daily_pnl[]`. This is the **exit P&L** if you close the spread on that day with the underlying at the optimal spot.

```markdown
### Daily P&L Projections

| Date | Days to Expiry | Best Exit Spot | Max P&L |
|------|----------------|---------------|---------|
| {date} | {days_to_short_expiry:.1f}d | ${optimal_spot} | ${pnl:,.2f} |
```

- Highlight the row with the highest `pnl` value with a `←` marker in the P&L column.
- `pnl` is already scaled by qty × 100 (total dollars).
- Negative P&L values: show in parentheses, e.g., `($1,234.56)`.

#### 3g. Roll Candidates

If `roll_candidates` is empty:
```markdown
### Roll Candidates

*No viable roll candidates found.*
```

Otherwise:
```markdown
### Roll Candidates

| # | Strike | Expiry | DTE | Delta | Assign% | IV | Net Credit | $/day | P&L if Assigned | Bid | Ask |
|---|--------|--------|-----|-------|---------|----|------------|-------|-----------------|-----|-----|
| 1 | ${strike} | {expiry → Mon DD} | {dte:.0f}d | {delta} | {assignment_prob}% | {iv_pct}% | ${net_credit:+.2f} | ${profit_per_day:.4f} | ${pnl_if_assigned:,.2f} | ${bid or "—"} | ${ask or "—"} |
```

- Net credit: show with sign (`+` = credit, `−` = debit).
- P&L if assigned negative: parentheses, e.g., `($358.00)`.
- All rolls capped at LEAPS expiry (`leaps_expiry`) — no roll will exceed it.

#### 3h. Comparison Table

```markdown
### Comparison

|  | Strike | Expiry | DTE | Delta | Assign% | $/day | P&L if Assigned |
|--|--------|--------|-----|-------|---------|-------|-----------------|
| **Current** | ${strike} | {Mon DD YYYY} | {dte:.1f}d | {delta} | {assignment_prob}% | ${profit_per_day:.4f} | ${pnl_if_assigned:,.2f} |
| Roll 1 | ... | ... | ... | ... | ... | ... | ... |
| Roll 2 | ... | ... | ... | ... | ... | ... | ... |
| Roll 3 | ... | ... | ... | ... | ... | ... | ... |
```

Only include Roll 2 / Roll 3 rows if they exist in `comparison`.

Bold the row with the best (lowest) assignment probability.

#### 3i. Recommendation

```markdown
### Recommendation

{One to three sentences. State: hold / roll / close, and which roll if applicable.
Reference the assignment probability, DTE, earnings context if relevant, and net credit.
If no rolls exist, say so and suggest hold or close.}
```

---

### 4. Footer

```markdown
---
*Generated by PMCC Advisor on {generated_at}*
```

---

## Formatting Conventions

| Data type | Format |
|-----------|--------|
| Prices / strikes | `$123.45` |
| Large P&L | `$1,234.56` or `($1,234.56)` for negative |
| Percentages | `28.4%` |
| Net credit with sign | `+$1.58` or `−$0.05` |
| DTE (fractional) | `6.5d` |
| Expiry dates | `May 08 2026` in headers; `May 08` in compact tables |
| Missing values | `—` |

## Expiry Conversion

Convert YYYYMMDD → human-readable:
- `20260508` → `May 08 2026` (full) or `May 08` (compact in tables)
- `20260918` → `Sep 18 2026`

# PMCC Scan Report — Claude Generation Template

This file defines the structure and requirements for Claude-generated PMCC reports.
When the user requests a report, run the scanner to get JSON data, then generate
the markdown report below using your analysis — not mechanical string formatting.

---

## Report Structure

### Header

```
# PMCC Scan Report
**Generated:** {generated_at}
**Symbols:** {comma-separated list}
**Criteria:** LEAPS ≥ {min_leaps_days}d · LEAPS δ {leaps_target_delta} · Short δ {short_target_delta}
```

---

### Section 1 — Scan Summary Table

One row per symbol, sorted by `pmcc_score` descending. Use these exact columns:

| Symbol | Price | IV% | Capital | Ann. Yield | Trend | Earnings | PMCC Score |
|--------|------:|----:|--------:|-----------:|-------|----------|:----------:|

Column definitions:
- **Symbol** — ticker
- **Price** — current stock price (`price`)
- **IV%** — ATM implied volatility (`iv_pct`)
- **Capital** — LEAPS cost basis (`leaps.mid × 100`, formatted as `$X,XXX`)
- **Ann. Yield** — annualized short-call yield estimate (`metrics.annual_yield_est_pct`)
- **Trend** — derive from `score_breakdown.trend_delta`: ≥1.5 → Bullish, ≤-1.5 → Bearish, >0 → Leaning Bull, <0 → Leaning Bear, 0 → Neutral
- **Earnings** — days to next earnings from `earnings_date`; flag with ⚠ if < 30 days; "passed" if in the past; "N/A" if unknown
- **PMCC Score** — `pmcc_score/max_possible_score`

---

### Section 2 — Per-Symbol Detail Sections

One section per symbol, in the same order as the summary table. Each section contains:

#### 2a. Section Header
```
### {SYMBOL} — Score {pmcc_score}/{max_possible_score}
```

#### 2b. LEAPS Table

| Expiry | Strike | Delta | IV% | Last | Bid | Ask | Mid | Capital |
|--------|-------:|------:|----:|-----:|----:|----:|----:|--------:|

Populate from `leaps.*`. IV% = `leaps.iv × 100`. Flag off-hours data: if `leaps.bid == 0 and leaps.ask == 0`, add note: `⚠ No live bid/ask — using last price`.

#### 2c. Short Call Table

| Expiry | Strike | Delta | IV% | Last | Bid | Ask | Mid | Premium | Yield% |
|--------|-------:|------:|----:|-----:|----:|----:|----:|--------:|-------:|

Populate from `short.*`. Premium = `short.mid × 100`. Yield% = `metrics.short_yield_pct`.
Flag wide spreads: if `short.spread_pct > 20`, add note: `⚠ Wide spread — use limit order at mid`.

#### 2d. Suggested PMCC Setup

Short bullet list:
- **Buy**: `{leaps.expiry}` `${leaps.strike}C` @ `${leaps.mid}` (δ `{leaps.delta}`)
- **Sell**: `{short.expiry}` `${short.strike}C` @ `${short.mid}` (δ `{short.delta}`)
- **Net Debit**: `${metrics.net_debit}` | **Max Risk**: `${metrics.capital_required}`
- **Max Profit**: `${metrics.max_profit}` | **Ann. Yield Est.**: `{metrics.annual_yield_est_pct}%`

#### 2e. Strengths

Bullet list of positive scoring factors from `score_breakdown`. Include:
- Delta accuracy (LEAPS and short)
- Liquidity (if scoring > 0)
- Spread quality (if scoring > 0)
- IV level and why it matters for this setup
- Yield quality
- Trend indicators that are positive
- Earnings clearance

Write each as a human-readable sentence, not a raw score string. Example:
- ✓ LEAPS delta 0.787 is on target (±0.05 of 0.80)
- ✓ Strong bullish trend: price above SMA50, RSI 76.8, MACD positive

#### 2f. Weaknesses

Bullet list of zero or negative scoring factors. Same style as Strengths.
If there are no weaknesses, write: `No material weaknesses identified.`

Highlight these risk factors explicitly when present:
- **LEAPS liquidity**: if vol+OI < 20, warn that fills may be difficult
- **LEAPS no bid/ask**: warn to confirm live market before entering
- **Wide short spread** (>20%): warn about slippage
- **Earnings within short expiry**: warn IV crush / gap risk
- **High IV** (>70%): warn expensive entry, IV crush exposure
- **Bearish trend**: note momentum is against the position

#### 2g. Verdict

One paragraph (3–5 sentences) synthesizing the setup. Cover:
1. Go / No-go recommendation with confidence level
2. The single most important supporting reason
3. The single biggest risk or watch item
4. Specific action advice (e.g., "use limit at mid", "wait for post-earnings reset", "confirm live bid before entry")

Lead with a bold label:
- **Go** — score ≥ 12
- **Go with notes** — score 10–11
- **Proceed with caution** — score 6–9
- **No-go** — score < 6

Separator: `---` between each symbol section.

---

## Tone and Style Requirements

- Write like an experienced options trader reviewing setups for a colleague
- Be direct and specific — reference actual numbers (deltas, spreads, IV%, etc.)
- Flag risks clearly, don't soften important warnings
- Keep each verdict paragraph tight: 3–5 sentences max
- No generic filler ("this is a solid stock" without data to back it) 
- Earnings proximity warnings must be explicit and actionable

---

## File Naming Convention

When saving to disk:
```
sandbox/PMCC_Scan_YYYY-MM-DD_HHmm.md
```
Use the `generated_at` timestamp from the JSON output.

---

## What NOT to include

- Do not reproduce the raw JSON or score breakdown strings verbatim
- Do not include implementation details (Black-Scholes, scoring algorithm internals)
- Do not speculate about future price direction beyond what the technicals indicate
- Do not recommend position sizing — that's the trader's job

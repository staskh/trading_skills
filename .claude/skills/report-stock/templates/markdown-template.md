# Stock Analysis Report - Markdown Template

Format the JSON data into a markdown report saved to `sandbox/`.

**Filename**: `{SYMBOL}_Analysis_Report_{YYYY-MM-DD}_{HHmm}.md`

## Report Structure

### 1. Header

```markdown
# {SYMBOL} Stock Analysis Report
**{company.name}** - Comprehensive Analysis
Generated: {generated}
```

### 2. Recommendation Box

```markdown
## Recommendation: {recommendation.recommendation}

**Strengths:**
- {strength 1}
- {strength 2}
...

**Risks:**
- {risk 1}
- {risk 2}
...
```

Use `recommendation.recommendation_level` to label: "positive" = BUY, "neutral" = HOLD, "negative" = AVOID.

### 3. Company Overview

| Metric | Value |
|--------|-------|
| Company | `company.name` |
| Sector | `company.sector` |
| Industry | `company.industry` |
| Market Cap | Format as `$X.XB` or `$X.XM` |
| Enterprise Value | Format as `$X.XB` or `$X.XM` |
| Beta | 2 decimals |

### 4. Trend Analysis

| Indicator | Value | Signal |
|-----------|-------|--------|
| Bullish Score | `X.XX / 8` | Strong(≥6)/Moderate(≥4)/Neutral(≥2)/Bearish(<2) |
| Price | `$X.XX` | - |
| 3-Month Return | `±X.X%` | Bullish/Bearish |
| vs SMA20 | `±X.X%` | Above/Below |
| vs SMA50 | `±X.X%` | Above/Below |
| RSI | `X.X` | Overbought(>70)/Oversold(<30)/Bullish(50-70)/Neutral |
| MACD | `X.XX vs Signal X.XX` | Bullish/Bearish |
| ADX | `X.X` | Strong(≥40)/Moderate(25-40)/Weak(<25) Trend |
| Next Earnings | `YYYY-MM-DD` | `BMO`/`AMC` |

**Signals:** List `trend_analysis.signals` as bullet points.

### 5. Fundamental Analysis

#### Valuation

| Metric | Value | Assessment |
|--------|-------|------------|
| Trailing P/E | `X.Xx` | Attractive(<15)/Reasonable(15-25)/Premium(>25) |
| Forward P/E | `X.Xx` | Same |
| Price/Book | `X.Xx` | - |
| EPS (TTM) | `$X.XX` | - |
| Forward EPS | `$X.XX` | - |

#### Profitability

| Metric | Value | Assessment |
|--------|-------|------------|
| Profit Margin | `X.X%` | Excellent(>20%)/Good(10-20%)/Low(<10%) |
| Operating Margin | `X.X%` | Same |
| ROE | `X.X%` | Same |
| ROA | `X.X%` | - |
| Revenue Growth | `±X.X%` | Growing/Declining |
| Earnings Growth | `±X.X%` | Growing/Declining |

#### Dividend & Balance Sheet

| Metric | Value | Assessment |
|--------|-------|------------|
| Dividend Yield | `X.XX%` or "None" | High(>5%)/Attractive(2-5%)/Low(<2%)/None |
| Dividend Rate | `$X.XX/share` | - |
| Payout Ratio | `X%` | At limit(>80%)/Moderate(50-80%)/Conservative(<50%) |
| Debt/Equity | `X.X%` | High(>100%)/Moderate(50-100%)/Low(<50%) |
| Current Ratio | `X.XXx` | Good(>1.5)/Adequate(1-1.5)/Low(<1) |

#### Earnings History

| Date | Estimate | Actual | Surprise |
|------|----------|--------|----------|
| YYYY-MM-DD | $X.XX | $X.XX | ±X.X% |

Up to 8 quarters.

### 6. Piotroski F-Score

**Score: X/9** ({piotroski.interpretation})

| Criteria | Result | Details |
|----------|--------|---------|
| 1. Positive Net Income | PASS/FAIL | Value |
| 2. Positive ROA | PASS/FAIL | Value |
| 3. Positive Operating CF | PASS/FAIL | Value |
| 4. CF > Net Income | PASS/FAIL | CF: X, NI: Y |
| 5. Lower Long-Term Debt | PASS/FAIL | Recent: X, Prev: Y |
| 6. Higher Current Ratio | PASS/FAIL | Recent: X, Prev: Y |
| 7. No Share Dilution | PASS/FAIL | Recent: X, Prev: Y |
| 8. Higher Gross Margin | PASS/FAIL | Recent: X, Prev: Y |
| 9. Higher Asset Turnover | PASS/FAIL | Recent: X, Prev: Y |

### 7. PMCC Viability

| Metric | Value | Assessment |
|--------|-------|------------|
| PMCC Score | `X / 11` | Excellent(≥9)/Good(7-8)/Acceptable(5-6)/Poor(<5) |
| Implied Volatility | `X.X%` | Ideal(25-50%)/Acceptable(20-60%)/High(>60%)/Low(<20%) |
| LEAPS Expiry | `YYYY-MM-DD (X days)` | - |
| LEAPS Strike | `$X` | - |
| LEAPS Delta | `0.XXX` | On Target(0.75-0.85)/Off Target |
| LEAPS Bid/Ask | `$X.XX / $X.XX` | - |
| LEAPS Spread | `X.X%` | Good(<10%)/Acceptable(10-20%)/Wide(>20%) |
| Short Expiry | `YYYY-MM-DD (X days)` | - |
| Short Strike | `$X` | - |
| Short Delta | `0.XXX` | On Target(0.15-0.25)/Off Target |
| Short Bid/Ask | `$X.XX / $X.XX` | - |
| Short Spread | `X.X%` | Good(<10%)/Acceptable(10-20%)/Wide(>20%) |

#### Trade Metrics

| Metric | Value |
|--------|-------|
| Net Debit | `$X,XXX.XX` |
| Short Yield (per cycle) | `X.XX%` |
| Estimated Annual Yield | `X.X%` |
| Max Profit (if assigned) | `$X,XXX.XX` |
| ROI at Max Profit | `X.X%` |
| Capital Required | `$X,XXX.XX` |

### 8. Option Spread Strategies

**Expiry:** {spread_strategies.expiry} ({spread_strategies.dte} days)

#### Strategy Summary

| Strategy | Direction | Max Profit | Max Loss | Risk/Reward | Breakeven |
|----------|-----------|------------|----------|-------------|-----------|
| Bull Call Spread | Bullish | $XXX | $XXX | X.XX | $XXX |
| Bear Put Spread | Bearish | $XXX | $XXX | X.XX | $XXX |
| Long Straddle | Neutral | Unlimited | $XXX | - | $XXX / $XXX |
| Long Strangle | Neutral | Unlimited | $XXX | - | $XXX / $XXX |
| Iron Condor | Neutral | $XXX | $XXX | X.XX | $XXX - $XXX |

#### Strategy Details

For each strategy, show legs, cost, breakeven, max profit/loss.

### 9. Investment Summary

**Strengths:**
- (from recommendation.strengths)

**Risk Factors:**
- (from recommendation.risks)

### Footer

```markdown
---
*This analysis is for informational purposes only and does not constitute financial advice.
Options trading involves significant risk of loss. Past performance is not indicative of future results.*
```

## Formatting Rules

- Percentages: Always show sign for changes (`+5.2%`, `-3.1%`)
- Currency: `$123.45`, `$1.2B`, `$45.6M`
- Ratios: 1 decimal for P/E, 2 decimals for delta/beta
- Scores: `X / max` format
- Missing data: "N/A" or "-"

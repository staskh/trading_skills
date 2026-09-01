---
name: stock-quote
description: Get real-time stock quote with price, volume, change, market cap, and 52-week range for any ticker symbol. Use when user asks about current stock price, quote, or basic stock info.
dependencies: ["trading-skills"]
---

# Stock Quote

Fetch current stock data from Yahoo Finance.

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

Run the quote script with the ticker symbol:

```bash
uv run python scripts/quote.py SYMBOL
```

Replace SYMBOL with the requested ticker (e.g., AAPL, MSFT, TSLA, SPY).

## Output

The script outputs JSON with:
- symbol, name, price, change, change_percent
- as_of_session, market_open_now
- volume, avg_volume, market_cap
- high_52w, low_52w, pe_ratio, dividend_yield

Present the data in a readable format. Highlight significant moves (>2% change).

**Before presenting `change`/`change_percent` as "today's move", check `as_of_session` against today's NY calendar date.** Before the regular session opens (`market_open_now: false` and `as_of_session` is a prior date), Yahoo's change fields still describe the *last completed session* (yesterday's close vs. the day before) — not intraday movement in the still-unopened current session. In that case, label it as "as of `<as_of_session>` close", not "today". Once `as_of_session` equals today's date, `change`/`change_percent` are genuinely intraday.

## Dependencies

- `yfinance`


## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.
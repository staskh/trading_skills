---
name: chart-ema-rsi
description: Renders a JPG chart of a ticker's daily candles with EMA 9/20 lines, their golden/death crossovers marked, and an RSI 14 panel with 70/30 bands. Use when the user asks for a chart, candle plot, EMA crossover chart or RSI chart of a stock.
dependencies: ["trading-skills"]
---

# Chart: EMA crossover and RSI

Daily candles from Yahoo with EMA(fast) and EMA(slow) over the price, a green ▲ under the
candle of each golden cross (fast crosses above slow) and a red ▼ over each death cross, and
RSI in a lower panel with 70/30 lines. Extra history is downloaded before the window, so the
lines are settled from the first plotted bar.

## Instructions

```bash
uv run python scripts/chart.py SYMBOL [--period 6mo] [--fast 9] [--slow 20] [--rsi 14] [--output PATH]
```

Show the user the image after it's written.

## Arguments

- `SYMBOL` - Ticker
- `--period` - Plotted window: `1mo`, `3mo`, `6mo` (default), `1y`, `2y`
- `--fast` / `--slow` - EMA lengths (default 9 / 20); fast must be shorter
- `--rsi` - RSI length (default 14)
- `--output` - JPG path (default `sandbox/<SYMBOL>_ema_rsi_YYYY-MM-DD_HHmm.jpg`)

## Output

JSON: `symbol`, `path`, `period`, `last_date`, `close`, `ema_fast_length`, `ema_slow_length`,
`ema_fast`, `ema_slow`, `trend` (`bullish` when fast is above slow), `rsi`, `crossovers`
(`date`, `type` golden/death, `ema_fast` at the cross) inside the window, `generated_at`,
`data_delay`; or `error`.

During market hours the last candle is today's partial bar.

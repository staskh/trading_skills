# massive — Massive (Polygon.io) API Integration

Functions backed by the [Massive.com](https://massive.com/) (formerly known as [Polygon.io](https://polygon.io)) API via the `massive` Python client.

## Setup

Set `MASSIVE_API_KEY` in your `.env` file:

```
MASSIVE_API_KEY=your_polygon_api_key
```

## Functions

### `option_whales(option_ticker, trading_date=None, sigma_z=3.5, return_all=False)`

Detects whale activity in one option contract from its 1-second bars on a single date.

- `invested = vwap × volume × 100` per bar.
- A bar is a whale when its Modified Z-Score (MAD-based) exceeds `sigma_z`, or it averages ≥ $1M per transaction.
- Flagged bars averaging ≤ $50k per transaction are dropped as retail noise.

**Returns:** `pd.DataFrame` sorted by timestamp ascending with columns
`timestamp`, `ticker`, `type`, `strike`, `expiry`, `close` (bar VWAP), `volume`, `transactions`, `invested`, `break_even`.
With `return_all=True`, returns `(outliers, all_bars)`.

```python
from trading_skills.massive import option_whales

whales = option_whales("O:NVDA260320P00170000", trading_date="2026-03-13")
print(whales[["timestamp", "volume", "close", "invested"]].to_string())
```

### `whales_hunter(underlying, max_months=2, precise=True, sigma_z=3.5)`

Scans an underlying over the latest and previous trading sessions:

1. Yahoo Finance chain screen selects candidate contracts (Modified Z-Score on daily invested, or volume > open interest).
2. If `precise` and `MASSIVE_API_KEY` is set, each candidate is drilled with `option_whales` on both sessions, and the underlying spot at trade time is attached.

Falls back to the Yahoo candidates (`source: "yahoo"`) when the key is missing or the drill-down finds no whales.

**Returns:** dict with `whales` (list of records, missing values as `None`), `source`, `trading_date`, `window_dates`.

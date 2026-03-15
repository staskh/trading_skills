# massive — Polygon.io API Integration

Functions backed by the [Massive.com](https://massive.com/) (formerly known as [Polygon.io](https://polygon.io)) API via the `massive` Python client.

## Setup

Set `MASSIVE_API_KEY` in your `.env` file:

```
MASSIVE_API_KEY=your_polygon_api_key
```

## Functions

### `option_whales(option_ticker, trading_date=None, sigma=6)`

Detects whale activity in a specific option contract using second-level (per-second) aggregation.

Fetches all 1-second bars for the contract on the given date, computes
`investment = volume × vwap` per bar, then returns bars where investment
exceeds `mean + sigma × std` of the population.

**Args:**
- `option_ticker` — option contract ticker (e.g. `"O:NVDA260320P00170000"`)
- `trading_date` — date to analyze (`date`, `datetime`, or `"YYYY-MM-DD"` string); defaults to latest NYSE trading day
- `sigma` — outlier threshold in standard deviations (default `6`)

**Returns:** `pd.DataFrame` sorted by `investment` descending with columns:
`timestamp`, `volume`, `vwap`, `investment`, `open`, `high`, `low`, `close`, `transactions`

**Example:**
```python
from trading_skills.massive import option_whales

whales = option_whales("O:NVDA260320P00170000", trading_date="2026-03-13", sigma=6)
print(whales[["timestamp", "volume", "vwap", "investment"]].to_string())
```

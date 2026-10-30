---
name: calendar
description: Report scheduled US economic events (CPI, NFP, FOMC, GDP, PCE, ISM, jobless claims...) with times in ET, impact, actual/consensus/previous. Use when user asks about the economic calendar, macro events, what data comes out today/this week, or release times. Optional ForexFactory cross-check for the current week.
dependencies: ["trading-skills"]
---

# Economic Calendar

Scheduled US economic releases per weekday, from Nasdaq's public economic-events feed
(through `trading_skills.economic_calendar`, which corrects the feed's day offset and
verifies each day against weekly releases with a fixed weekday).

## Instructions

> **Note:** If `uv` is not installed or `pyproject.toml` is not found, replace `uv run python` with `python` in all commands below.

```bash
uv run python scripts/events.py [--date YYYY-MM-DD] [--days N] [--impact all|high] [--forexfactory]
```

## Arguments

- `--date` - First day, YYYY-MM-DD (default: today ET). A weekend rolls to Monday.
- `--days` - Number of weekdays to report (default: 1). Weekends are skipped.
- `--impact` - `all` (default) or `high` (FOMC, CPI, PPI, PCE, NFP, unemployment, GDP, retail sales, ISM, Fed-chair remarks).
- `--forexfactory` - Also fetch ForexFactory's calendar and cross-check each day. ForexFactory publishes **only the current Sun–Sat week**; other days report `available: false`. The feed rate-limits to about one request per 5 minutes, so the week is cached in the system temp dir for an hour (an older copy is used if a fetch fails).

## Output

- `generated_at`, `data_delay`, `source` (`"nasdaq"`)
- `days` - one entry per weekday:
  - `date`, `weekday`
  - `verified` - true when the day's contents matched the requested weekday; false means use with care
  - `feed_date` - the Nasdaq `date` parameter whose rows were used
  - `events` - list of `{event, time_et, impact, actual, consensus, previous}`, high-impact first; `null` when the calendar is unavailable or unverifiable (`note` says to verify manually — never read null as a quiet day)
  - `forexfactory` (with `--forexfactory`) - `{available, events, cross_check}` or `{available: false, note}`
    - `cross_check.confirmed` - same release at the same time in both sources
    - `cross_check.time_mismatch` - same release, different time (check which time is right)
    - `cross_check.missing_in_nasdaq` - high/medium ForexFactory release Nasdaq lacks
    - `cross_check.nasdaq_only` - high-impact Nasdaq release ForexFactory lacks

## Examples

```bash
# Today
uv run python scripts/events.py

# Yesterday and today, high impact only, cross-checked
uv run python scripts/events.py --date 2026-10-29 --days 2 --impact high --forexfactory

# Next week
uv run python scripts/events.py --date 2026-11-02 --days 5 --impact high
```

## Reporting

Group by day; lead with high-impact releases and their ET times. Flag any day with
`events: null` or `verified: false`, and every `time_mismatch` / `missing_in_nasdaq`
from the cross-check. FOMC decision days come from a hardcoded schedule and are
always included.

## Dependencies

- `requests`

## Timezone

All timestamps and time-based calculations must use the `America/New_York` timezone. All JSON output must include `generated_at` (NY time string) and `data_delay` fields.

---
name: ib-multileg-options
description: Propose multi-leg option trades (Iron Duck, Reverse Iron Duck, broken-wing iron butterfly, delta-neutral/directional/broken-wing butterflies, Big Beak/Small Beak/Flat Head woodpeckers, Time Fly) from the Interactive Brokers option chain. Classifies market direction and IV regime, picks strikes by delta and an expiry by DTE, validates POP / upside risk / break-even loss, and returns exit levels and position sizing. Use when the user asks which multi-leg/income options trade to put on, for Iron Duck or butterfly setups, or for strikes by delta. Requires TWS or IB Gateway running locally. Proposals only, never places orders.
dependencies: ["trading-skills"]
---

# IB Multi-Leg Options

Implements the NavigationTrading course rules (Iron Duck, Dynamic Butterflies, Time Fly) as an algorithm.
- `references/multileg_options_algorithm.md` has the full rules, with [C] marking course rules and [A] marking assumptions.
- `references/multileg_options_config.yaml` has every parameter, including deltas, DTE windows, POP thresholds, exits and risk limits. Edit the YAML to tune; don't hard-code values.

## Prerequisites

TWS or IB Gateway running locally with the API enabled:
- Paper trading: port 7497
- Live trading: port 7496 (default)

Market data subscriptions give real-time quotes and greeks. Without them, IB returns delayed or frozen data.

## Instructions

Auto mode picks strategies from the regime:
```bash
uv run python scripts/multileg.py SPX --dte 14
```

Specific strategies or expiry, with sizing:
```bash
uv run python scripts/multileg.py SPY --strategy iron_duck,bw_iron_butterfly --expiry 20261016 --account-value 50000 --port 7497
```

Every strategy, regardless of regime:
```bash
uv run python scripts/multileg.py RUT --strategy all
```

## Arguments

- `SYMBOL`: SPX, RUT, NDX and XSP are traded as cash-settled indexes. Anything else is treated as a stock or ETF.
- `--dte N`: target days to expiry (default 14). The nearest listed expiry is used.
- `--expiry YYYYMMDD`: exact expiry. Overrides `--dte`.
- `--strategy`: comma list or `all`. Names: `iron_duck, reverse_iron_duck, bw_iron_butterfly, jade_lizard, dn_fly, bull_fly, bear_fly, bull_bwb, bear_bwb, neutral_bwb, big_beak, small_beak, flat_head, time_fly`.
- `--direction BULL|BEAR|NEUTRAL`: overrides the EMA-based direction signal.
- `--earnings`: an earnings event falls before expiry. Restricts selection to Iron Duck.
- `--account-value`: sizes each trade at 5% of the account per position.
- `--include-disabled`: allows the Jade Lizard (undefined risk).
- `--config PATH`: alternate YAML config.
- `--port`: IB port (default 7496).

## How it works

1. Fetches spot, 1 year of daily bars, and 1 year of IB option-implied-volatility history.
2. Classifies the regime:
   - **direction:** EMA 20/50, 5-day slope, 1×ATR neutral band
   - **IV level:** IV Rank of 50 or more is HIGH; under 25 is LOW
   - **IV trend:** EXPANDING, FLAT or CONTRACTING, using a ±2% band
   - **skew:** CALL_RICH when the 25Δ call IV exceeds the 25Δ put IV
3. Selects strategies with the doc §4 matrix. Butterfly-family trades are gated off when IV is contracting, and Time Fly needs IV expanding.
4. Fetches the chain for the expiry (strikes within ~3σ), with deltas from IB model greeks. If greeks are missing, it falls back to Black-Scholes using IV solved from the mid.
5. Builds the legs by delta. For example, the Iron Duck sells the 65Δ call, buys 1 strike higher, sells the 15Δ put and buys the 10Δ put.
6. Analyzes each trade (expiry P/L, breakevens, lognormal POP, theoretical loss at the downside break-even) and runs the strategy's checks. If a check fails, it searches nearby strikes, ±1 and ±2 per anchor.
7. Returns exit levels (stop or target combo prices, alert and break-even prices, time exit) and optional sizing.

## Output

JSON with:
- `regime`: direction, iv_level, iv_trend, iv_rank, call_rich, plus the EMA/ATR details
- `recommended`: the first candidate with status `valid`, in priority order
- `candidates[]`, each with:
  - `status`: `valid`, `failed_validation`, `gated`, `skipped: … DTE outside …`, `disabled_in_config`, or `build_failed`
  - `legs[]`: action, qty, right, strike, expiry, delta, iv, bid, ask, mid
  - `analysis`: net_price (+credit / −debit, per share), max_profit, max_loss, breakevens, pop, upside/downside P/L at expiry, theoretical_loss_at_downside_be
  - `checks`: each validation rule as true or false
  - `liquidity`: leg and combo bid/ask widths
  - `exit_plan`: concrete stop / target / alert / time-exit levels, plus adjustments
  - `sizing`: only when `--account-value` is given
- `warnings`, `generated_at`, `data_delay`

Present the regime first. Then show the recommended trade as a leg table, with credit or debit, max profit and loss, POP, breakevens and the exit plan. List the other candidates briefly with their status and the checks that failed. Always say that this is a proposal: no order was placed, and the user must review it and enter it themselves.

## Caveats

- IB snapshot tickers don't include open interest, so the liquidity check uses bid/ask width only. Check OI before trading.
- POP is lognormal, using ATM IV. It doesn't account for skew, so it may differ from the broker's figure.
- Values tagged [A] in the config are assumptions to backtest and tune.

## Dependencies

- `ib-async`, `pyyaml`, `scipy`, `numpy`

## Timezone

All timestamps use `America/New_York`. JSON output includes `generated_at` and `data_delay`.

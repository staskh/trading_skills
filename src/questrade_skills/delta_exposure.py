# ABOUTME: Delta-adjusted notional exposure for a Questrade portfolio.
# ABOUTME: Reuses trading_skills Black-Scholes; spot via yfinance. Read-only.

from datetime import date, datetime

from trading_skills.black_scholes import black_scholes_delta, estimate_iv

from questrade_skills.connection import get_accounts, get_symbols, qt_get

RISK_FREE_RATE = 0.05
OPTION_MULTIPLIER = 100


def _spot_prices(symbols: set[str]) -> dict[str, float]:
    """Best-effort spot prices via yfinance (delayed is fine for a risk read).

    Imported lazily so the module loads even where yfinance is absent.
    """
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}
    prices = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).fast_info
            px = info.get("last_price") or info.get("lastPrice")
            if px:
                prices[sym] = float(px)
        except Exception:
            continue
    return prices


def _parse_expiry(raw: str) -> date:
    """Questrade optionExpiryDate is ISO like 2026-01-16T00:00:00.000000-05:00."""
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()


def get_delta_exposure(account: str | None = None, all_accounts: bool = True) -> dict:
    """Compute delta-adjusted notional exposure by underlying and account."""
    try:
        accounts = get_accounts()
        if not accounts:
            return {"connected": True, "error": "No accounts found on this login"}
        numbers = [a["number"] for a in accounts]
        targets = numbers if all_accounts else [account] if account else [numbers[0]]

        # 1. Gather positions across target accounts.
        raw = []
        for num in targets:
            data = qt_get(f"/v1/accounts/{num}/positions")
            for p in data.get("positions", []):
                raw.append((num, p))

        # 2. Classify positions (Stock vs Option) via batched symbol lookup.
        ids = [p["symbolId"] for _, p in raw if p.get("symbolId")]
        details = get_symbols(ids)

        # 3. Determine the underlying tickers we need spot prices for.
        needed = set()
        for _, p in raw:
            d = details.get(p.get("symbolId"), {})
            if d.get("securityType") == "Option":
                needed.add(d.get("optionRoot") or p.get("symbol"))
            else:
                needed.add(p.get("symbol"))
        spot_prices = _spot_prices(needed)

        today = date.today()
        results = []

        for acct, p in raw:
            d = details.get(p.get("symbolId"), {})
            sec = d.get("securityType")
            qty = p.get("openQuantity") or 0

            if sec == "Option":
                underlying = d.get("optionRoot") or p.get("symbol")
                strike = d.get("optionStrikePrice")
                spot = spot_prices.get(underlying) or (strike * 0.95 if strike else None)
                if not (strike and spot):
                    continue
                expiry = _parse_expiry(d["optionExpiryDate"])
                dte_years = max((expiry - today).days / 365.0, 0.001)
                opt_type = "call" if (d.get("optionType") or "").lower() == "call" else "put"
                iv = estimate_iv(spot, strike, dte_years, opt_type)
                delta = black_scholes_delta(
                    spot, strike, dte_years, RISK_FREE_RATE, iv, opt_type
                )
                raw_notional = spot * qty * OPTION_MULTIPLIER
                delta_notional = delta * raw_notional
                results.append(
                    {
                        "account": acct,
                        "underlying": underlying,
                        "sec_type": "OPT",
                        "option_type": opt_type,
                        "strike": strike,
                        "expiry": expiry.isoformat(),
                        "qty": qty,
                        "spot": round(spot, 2),
                        "delta": round(delta, 4),
                        "delta_notional": round(delta_notional, 2),
                    }
                )
            else:
                spot = spot_prices.get(p.get("symbol")) or p.get("currentPrice")
                if not spot:
                    continue
                delta_notional = spot * qty
                results.append(
                    {
                        "account": acct,
                        "underlying": p.get("symbol"),
                        "sec_type": "STK",
                        "qty": qty,
                        "spot": round(spot, 2),
                        "delta": 1.0,
                        "delta_notional": round(delta_notional, 2),
                    }
                )

        # 4. Aggregate.
        by_underlying: dict[str, float] = {}
        by_account: dict[str, float] = {}
        for r in results:
            by_underlying[r["underlying"]] = (
                by_underlying.get(r["underlying"], 0) + r["delta_notional"]
            )
            by_account[r["account"]] = by_account.get(r["account"], 0) + r["delta_notional"]

        return {
            "connected": True,
            "accounts": targets,
            "note": "Deltas are Black-Scholes model estimates (estimated IV); "
            "spot prices are delayed via yfinance.",
            "positions": results,
            "delta_notional_by_underlying": {
                k: round(v, 2) for k, v in sorted(by_underlying.items())
            },
            "delta_notional_by_account": {k: round(v, 2) for k, v in by_account.items()},
            "total_delta_notional": round(sum(by_account.values()), 2),
        }
    except ConnectionError as e:
        return {"connected": False, "error": str(e)}

# ABOUTME: Scans symbols for bullish trends and ranks them by composite score.
# ABOUTME: Uses SMA, RSI, MACD, ADX indicators plus momentum.

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

from trading_skills.earnings import get_earnings_info
from trading_skills.technicals import compute_raw_indicators


def compute_bullish_score(symbol: str, period: str = "3mo", ticker=None) -> dict | None:
    """Compute bullish trend score for a symbol.

    Score components (higher = more bullish):
    - Price above SMA20: +1, above SMA50: +1
    - RSI between 50-70: +1 (healthy bullish), 30-50: +0.5
    - MACD above signal: +1, histogram rising: +0.5
    - ADX > 25 with +DI > -DI: +1.5 (strong bullish trend)
    - Price momentum (% change over period): weighted contribution
    """
    try:
        ticker = ticker or yf.Ticker(symbol)
        df = ticker.history(period=period)

        if df.empty or len(df) < 50:
            return None

        earnings_info = get_earnings_info(symbol)
        next_earnings = earnings_info.get("earnings_date")
        earnings_timing = earnings_info.get("timing")

        score = 0.0
        signals = []
        current_price = df["Close"].iloc[-1]

        period_return = (current_price / df["Close"].iloc[0] - 1) * 100

        raw = compute_raw_indicators(df)

        # SMA analysis
        sma20_val = raw["sma20"]
        sma50_val = raw["sma50"]

        if sma20_val is not None:
            if current_price > sma20_val:
                score += 1.0
                signals.append("Above SMA20")
            pct_from_sma20 = ((current_price - sma20_val) / sma20_val) * 100
        else:
            pct_from_sma20 = 0

        if sma50_val is not None:
            if current_price > sma50_val:
                score += 1.0
                signals.append("Above SMA50")
            pct_from_sma50 = ((current_price - sma50_val) / sma50_val) * 100
        else:
            pct_from_sma50 = 0

        # RSI analysis
        rsi_val = raw["rsi"]
        if rsi_val is not None:
            if 50 <= rsi_val <= 70:
                score += 1.0
                signals.append(f"RSI bullish ({rsi_val:.1f})")
            elif 30 <= rsi_val < 50:
                score += 0.5
                signals.append(f"RSI neutral ({rsi_val:.1f})")
            elif rsi_val < 30:
                score += 0.25
                signals.append(f"RSI oversold ({rsi_val:.1f})")

        # MACD analysis
        macd_val = raw["macd_line"]
        macd_signal = raw["macd_signal"]
        macd_hist = raw["macd_hist"]
        prev_hist = raw["prev_macd_hist"]

        if macd_val is not None and macd_signal is not None:
            if macd_val > macd_signal:
                score += 1.0
                signals.append("MACD above signal")
        if macd_hist is not None and prev_hist is not None:
            if macd_hist > prev_hist:
                score += 0.5
                signals.append("MACD momentum rising")

        # ADX analysis
        adx_val = raw["adx"]
        dmp = raw["dmp"]
        dmn = raw["dmn"]

        if adx_val is not None and dmp is not None and dmn is not None:
            if adx_val > 25 and dmp > dmn:
                score += 1.5
                signals.append(f"Strong bullish trend (ADX={adx_val:.1f})")
            elif dmp > dmn:
                score += 0.5
                signals.append("Bullish direction (+DI > -DI)")

        # Momentum bonus (capped)
        momentum_bonus = min(max(period_return / 20, -1), 2)
        score += momentum_bonus

        return {
            "symbol": symbol,
            "score": round(score, 2),
            "price": round(current_price, 2),
            "next_earnings": next_earnings,
            "earnings_timing": earnings_timing,
            "period_return_pct": round(period_return, 2),
            "pct_from_sma20": round(pct_from_sma20, 2),
            "pct_from_sma50": round(pct_from_sma50, 2),
            "rsi": round(rsi_val, 2) if rsi_val else None,
            "macd": round(macd_val, 4) if macd_val else None,
            "macd_signal": round(macd_signal, 4) if macd_signal else None,
            "macd_hist": round(macd_hist, 4) if macd_hist else None,
            "adx": round(adx_val, 2) if adx_val else None,
            "dmp": round(dmp, 2) if dmp else None,
            "dmn": round(dmn, 2) if dmn else None,
            "signals": signals,
        }
    except Exception as e:
        print(f"Error processing {symbol}: {e}", file=sys.stderr)
        return None


def scan_symbols(
    symbols: list[str], top_n: int = 30, period: str = "3mo", workers: int = 10
) -> list[dict]:
    """Scan all symbols and return top N by bullish score."""
    results = []
    total = len(symbols)

    print(f"Scanning {total} symbols...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(compute_bullish_score, sym, period): sym for sym in symbols}

        for i, future in enumerate(as_completed(futures), 1):
            symbol = futures[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                if i % 50 == 0:
                    print(f"  Processed {i}/{total}...", file=sys.stderr)
            except Exception as e:
                print(f"  Failed {symbol}: {e}", file=sys.stderr)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]

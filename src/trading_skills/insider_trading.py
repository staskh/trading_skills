# ABOUTME: Fetches insider trading activity (SEC Form 4) from Yahoo Finance.
# ABOUTME: Returns transactions, net sentiment, and multi-ticker comparisons.

import re
from datetime import datetime, timedelta

import yfinance as yf


def _parse_price_from_text(text: str) -> float | None:
    """Extract price from yfinance text field like 'Sale at price 275.00 per share'."""
    if not text:
        return None
    match = re.search(r"at price\s+([\d.]+)", str(text))
    return float(match.group(1)) if match else None


def _classify_transaction(transaction: str, text: str = "") -> str:
    """Map transaction type from the Transaction or Text field."""
    combined = (str(transaction) + " " + str(text)).lower()
    if not combined.strip():
        return "other"
    if any(k in combined for k in ("sale", "sell", "sold")):
        return "sell"
    if any(k in combined for k in ("purchase", "buy", "bought")):
        return "buy"
    if any(k in combined for k in ("exercise", "option", "conversion")):
        return "exercise"
    return "other"


def _row_to_transaction(row) -> dict:
    shares = row.get("Shares")
    value = row.get("Value")
    text = str(row.get("Text", ""))
    transaction_str = str(row.get("Transaction", ""))
    start_date = row.get("Start Date")

    # Derive price per share
    price_per_share = None
    if shares and value and shares != 0:
        try:
            price_per_share = round(float(value) / float(shares), 2)
        except (TypeError, ZeroDivisionError):
            pass
    if price_per_share is None:
        price_per_share = _parse_price_from_text(text)

    # Format date
    if hasattr(start_date, "strftime"):
        date_str = start_date.strftime("%Y-%m-%d")
    elif start_date is not None:
        date_str = str(start_date)[:10]
    else:
        date_str = None

    return {
        "insider": str(row.get("Insider", "")),
        "role": str(row.get("Position", "")),
        "transaction": transaction_str,
        "transaction_type": _classify_transaction(transaction_str, text),
        "shares": int(shares) if shares is not None else None,
        "price": price_per_share,
        "value": round(float(value), 2) if value and str(value) != "nan" else None,
        "date": date_str,
        "ownership": str(row.get("Ownership", "")),
    }


def get_insider_transactions(symbol: str, days_back: int = 90, ticker=None) -> dict:
    """Fetch and summarize insider transactions for a single symbol."""
    ticker = ticker or yf.Ticker(symbol)

    try:
        df = ticker.insider_transactions
    except Exception as e:
        return {"symbol": symbol, "error": f"Failed to fetch insider data: {e}"}

    if df is None or df.empty:
        return {"symbol": symbol, "transactions": [], "summary": _empty_summary()}

    # Filter to trailing window
    cutoff = datetime.now() - timedelta(days=days_back)
    df = df.copy()
    df["_date"] = df["Start Date"].apply(
        lambda d: d.to_pydatetime() if hasattr(d, "to_pydatetime") else datetime.min
    )
    df = df[df["_date"] >= cutoff]

    transactions = [_row_to_transaction(row) for _, row in df.iterrows()]
    summary = _compute_summary(transactions)

    return {
        "symbol": symbol,
        "days_back": days_back,
        "count": len(transactions),
        "transactions": transactions,
        "summary": summary,
    }


def _empty_summary() -> dict:
    return {
        "net_sentiment": "neutral",
        "buy_count": 0,
        "sell_count": 0,
        "buy_value": 0,
        "sell_value": 0,
        "net_value": 0,
    }


def _compute_summary(transactions: list[dict]) -> dict:
    buys = [t for t in transactions if t["transaction_type"] == "buy"]
    sells = [t for t in transactions if t["transaction_type"] == "sell"]

    buy_value = sum(t["value"] for t in buys if t["value"])
    sell_value = sum(t["value"] for t in sells if t["value"])
    net_value = buy_value - sell_value

    if net_value > 0:
        sentiment = "net_buying"
    elif net_value < 0:
        sentiment = "net_selling"
    else:
        sentiment = "neutral"

    return {
        "net_sentiment": sentiment,
        "buy_count": len(buys),
        "sell_count": len(sells),
        "buy_value": round(buy_value, 2),
        "sell_value": round(sell_value, 2),
        "net_value": round(net_value, 2),
    }


def get_multiple_insider_transactions(symbols: list[str], days_back: int = 90) -> dict:
    """Fetch insider transactions for multiple symbols and rank by net sentiment."""
    results = []
    for symbol in symbols:
        data = get_insider_transactions(symbol, days_back)
        results.append(data)

    # Rank by net_value descending (most buying first)
    ranked = sorted(
        results,
        key=lambda r: r.get("summary", {}).get("net_value", 0),
        reverse=True,
    )

    return {
        "symbols": symbols,
        "days_back": days_back,
        "results": ranked,
    }

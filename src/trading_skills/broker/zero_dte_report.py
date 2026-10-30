# ABOUTME: Aggregates ib_0dte sandbox artifacts into a paper-test summary.
# ABOUTME: Entry/stop stats come from saved *_exec_*.json; outcomes from the daily-log markdown.

import json
from collections import Counter
from pathlib import Path


def _to_float(text) -> float | None:
    """Parse a table cell to a float, tolerating $, commas, +, blanks."""
    if text is None:
        return None
    s = str(text).strip().replace("$", "").replace(",", "").replace("+", "")
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Entry side — from saved execute JSONs
# --------------------------------------------------------------------------- #
def extract_entry(data: dict) -> dict | None:
    """Pull the executed spread's entry facts + placed stop levels from one JSON.

    Returns None if the file isn't a filled execution with an attached bracket.
    """
    order = data.get("order") or {}
    bracket = order.get("bracket") or {}
    if not order.get("ok") or not bracket.get("stops"):
        return None

    candidates = data.get("candidates") or []
    picked = data.get("picked")
    cand = None
    if picked and 1 <= picked <= len(candidates):
        cand = candidates[picked - 1]
    cand = cand or data.get("best") or {}

    return {
        "symbol": data.get("symbol"),
        "spread_type": data.get("spread_type"),
        "expiry": data.get("expiry"),
        "short_delta": cand.get("short_delta"),
        "credit": cand.get("net_credit"),
        "pop": cand.get("pop"),
        "contracts": cand.get("contracts"),
        "capital_at_risk": cand.get("max_loss_total"),
        "stop_bindings": [s.get("binding") for s in bracket["stops"] if s.get("binding")],
    }


def aggregate_entries(entries: list[dict]) -> dict:
    """Summarize entry-side facts across placed trades."""
    if not entries:
        return {"placed": 0}
    deltas = [e["short_delta"] for e in entries if e.get("short_delta") is not None]
    pops = [e["pop"] for e in entries if e.get("pop") is not None]
    car = [e["capital_at_risk"] for e in entries if e.get("capital_at_risk") is not None]
    bindings = Counter(b for e in entries for b in e.get("stop_bindings", []))
    return {
        "placed": len(entries),
        "by_symbol": dict(Counter(e["symbol"] for e in entries)),
        "by_type": dict(Counter(e["spread_type"] for e in entries)),
        "short_delta_avg": round(sum(deltas) / len(deltas), 3) if deltas else None,
        "short_delta_range": [min(deltas), max(deltas)] if deltas else None,
        "pop_avg": round(sum(pops) / len(pops), 3) if pops else None,
        "capital_at_risk_total": round(sum(car), 2) if car else None,
        "stop_binding_placed": dict(bindings),
    }


def load_entries(paths: list[Path]) -> list[dict]:
    """Read and extract entries from a list of JSON paths (skipping bad/irrelevant)."""
    out = []
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entry = extract_entry(data)
        if entry:
            out.append(entry)
    return out


# --------------------------------------------------------------------------- #
# Outcome side — from the daily-log markdown
# --------------------------------------------------------------------------- #
# Daily Log columns (0-indexed after splitting on '|'):
# 0:# 1:Date 2:Regime 3:Symbol 4:Type 5:ShortD 6:Width 7:Qty 8:Credit 9:POP
# 10:Closed by 11:P&L 12:Event 13:Notes
def parse_log(text: str) -> list[dict]:
    """Parse filled Daily-Log rows (any row whose P&L cell is numeric)."""
    rows = []
    in_daily = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Daily Log"):
            in_daily = True
            continue
        if in_daily and stripped.startswith("### "):
            break  # reached the legend — table is done
        if not (in_daily and stripped.startswith("|")):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 14 or not cells[0].isdigit():
            continue  # header / separator / non-data row
        pnl = _to_float(cells[11])
        if pnl is None:
            continue  # not yet resolved
        rows.append(
            {
                "date": cells[1],
                "symbol": cells[3],
                "type": cells[4],
                "closed_by": (cells[10] or "").lower() or None,
                "pnl": pnl,
                "event": (cells[12] or "").lower() or None,
            }
        )
    return rows


def pnl_stats(rows: list[dict]) -> dict:
    """Win rate, avg win/loss, expectancy, max drawdown, and exit-leg mix."""
    if not rows:
        return {"trades": 0}
    pnls = [r["pnl"] for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    # Max peak-to-trough drawdown of the cumulative P&L (rows in log order).
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    decided = len(wins) + len(losses)
    return {
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(rows) - decided,
        "win_rate": round(len(wins) / decided, 3) if decided else None,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "total_pnl": round(sum(pnls), 2),
        "expectancy_per_trade": round(sum(pnls) / len(rows), 2),
        "max_drawdown": round(max_dd, 2),
        "closed_by": dict(Counter(r["closed_by"] for r in rows if r["closed_by"])),
        "by_event": dict(Counter(r["event"] for r in rows if r["event"])),
    }


def build_report(entries: list[dict], log_rows: list[dict]) -> dict:
    """Combined report: entry-side aggregates + outcome-side P&L stats."""
    return {"entries": aggregate_entries(entries), "outcomes": pnl_stats(log_rows)}

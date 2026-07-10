#!/usr/bin/env python3
# ABOUTME: Aggregate ib_0dte paper-test artifacts into a readable summary.
# ABOUTME: Entry/stop stats from sandbox/*_exec_*.json; outcomes from the daily-log markdown.

import argparse
import json
from pathlib import Path

from trading_skills.broker.zero_dte_report import build_report, load_entries, parse_log


def _sandbox_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent / "sandbox"
    return Path.cwd() / "sandbox"


def _fmt(d: dict) -> str:
    return json.dumps(d, indent=2, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description="Summarize ib_0dte paper-test logs")
    ap.add_argument("--dir", default=None, help="Directory of artifacts (default: repo sandbox/)")
    ap.add_argument(
        "--log", default=None, help="Daily-log .md (default: latest paper_test_log_*.md)"
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = ap.parse_args()

    d = Path(args.dir) if args.dir else _sandbox_dir()

    entry_files = sorted(d.glob("*_exec_*.json"))
    entries = load_entries(entry_files)

    log_path = Path(args.log) if args.log else None
    if log_path is None:
        logs = sorted(d.glob("ib_0dte_paper_test_log_*.md"))
        log_path = logs[-1] if logs else None
    log_rows = parse_log(log_path.read_text(encoding="utf-8")) if log_path else []

    report = build_report(entries, log_rows)
    report["sources"] = {
        "exec_json_files": len(entry_files),
        "log_file": str(log_path) if log_path else None,
    }

    if args.json:
        print(_fmt(report))
        return

    e, o = report["entries"], report["outcomes"]
    print("=== ib_0dte paper-test report ===")
    print(f"sources: {len(entry_files)} exec JSON files | log: {log_path}")
    print()
    print(f"ENTRIES placed: {e.get('placed', 0)}")
    if e.get("placed"):
        print(f"  by symbol: {e['by_symbol']}")
        print(f"  by type:   {e['by_type']}")
        print(f"  short delta: avg {e['short_delta_avg']} range {e['short_delta_range']}")
        print(f"  avg POP: {e['pop_avg']} | capital at risk total: ${e['capital_at_risk_total']}")
        print(f"  stop level PLACED (binding): {e['stop_binding_placed']}")
    print()
    print(f"OUTCOMES (from filled log rows): {o.get('trades', 0)} resolved trades")
    if o.get("trades"):
        print(
            f"  win rate: {o['win_rate']} ({o['wins']}W/{o['losses']}L/{o['scratches']}scr)"
        )
        print(f"  avg win: ${o['avg_win']} | avg loss: ${o['avg_loss']}")
        print(f"  expectancy: ${o['expectancy_per_trade']}/trade | total P&L: ${o['total_pnl']}")
        print(f"  max drawdown: ${o['max_drawdown']}")
        print(f"  CLOSED BY (actual): {o['closed_by']}")
        if o.get("by_event"):
            print(f"  by event: {o['by_event']}")
    else:
        print("  (no resolved trades logged yet - fill the P&L column in the daily log)")


if __name__ == "__main__":
    main()

# ABOUTME: Tests for the ib_0dte paper-test report aggregator (pure functions).
# ABOUTME: Covers entry extraction, log parsing, and P&L stats incl. drawdown.

from trading_skills.broker.zero_dte_report import (
    aggregate_entries,
    extract_entry,
    parse_log,
    pnl_stats,
)


class TestExtractEntry:
    def _exec_json(self):
        return {
            "symbol": "NDX",
            "spread_type": "bear_call",
            "expiry": "20260710",
            "picked": 1,
            "candidates": [
                {
                    "short_delta": 0.18,
                    "net_credit": 0.85,
                    "pop": 0.84,
                    "contracts": 3,
                    "max_loss_total": 2905.0,
                },
            ],
            "best": {"short_delta": 0.18},
            "order": {
                "ok": True,
                "bracket": {"stops": [{"binding": "premium"}]},
            },
        }

    def test_extracts_entry_and_binding(self):
        e = extract_entry(self._exec_json())
        assert e["symbol"] == "NDX"
        assert e["short_delta"] == 0.18
        assert e["credit"] == 0.85
        assert e["capital_at_risk"] == 2905.0
        assert e["stop_bindings"] == ["premium"]

    def test_dryrun_or_unfilled_is_ignored(self):
        assert extract_entry({"order": None}) is None
        assert extract_entry({"order": {"ok": False}}) is None
        assert extract_entry({"order": {"ok": True, "bracket": {"stops": []}}}) is None


class TestAggregateEntries:
    def test_aggregates_counts_and_bindings(self):
        entries = [
            {
                "symbol": "NDX",
                "spread_type": "bear_call",
                "short_delta": 0.18,
                "pop": 0.84,
                "capital_at_risk": 2905.0,
                "stop_bindings": ["premium"],
            },
            {
                "symbol": "NDX",
                "spread_type": "bull_put",
                "short_delta": 0.12,
                "pop": 0.9,
                "capital_at_risk": 1000.0,
                "stop_bindings": ["strike"],
            },
        ]
        agg = aggregate_entries(entries)
        assert agg["placed"] == 2
        assert agg["by_symbol"] == {"NDX": 2}
        assert agg["by_type"] == {"bear_call": 1, "bull_put": 1}
        assert agg["short_delta_range"] == [0.12, 0.18]
        assert agg["capital_at_risk_total"] == 3905.0
        assert agg["stop_binding_placed"] == {"premium": 1, "strike": 1}

    def test_empty(self):
        assert aggregate_entries([]) == {"placed": 0}


# 14 columns; parse_log keys off column position, so short headers are fine here.
LOG = """
## Daily Log

| # | Date | Reg | Sym | Type | SD | W | Q | Cr | POP | Closed | PnL | Ev | N |
|-|-|-|-|-|-|-|-|-|-|-|-|-|-|
| 1 | 2026-07-10 |  | NDX | bear_call | 0.18 | 10 | 3 | 0.85 | 0.84 | target | 128 |  |  |
| 2 | 2026-07-13 |  | NDX | bear_call | 0.20 | 10 | 3 | 0.90 | 0.80 | stop-premium | -415 |  |  |
| 3 | 2026-07-14 |  | SPX | bull_put | 0.15 | 5 | 2 | 0.60 | 0.85 | time-exit | 40 |  |  |
| 4 | 2026-07-15 |  |  |  |  |  |  |  |  |  |  |  |  |

### Column legend
- stuff
"""


class TestParseLog:
    def test_parses_only_filled_rows(self):
        rows = parse_log(LOG)
        assert len(rows) == 3  # row 4 has no P&L
        assert rows[0]["closed_by"] == "target"
        assert rows[1]["pnl"] == -415.0
        assert rows[2]["symbol"] == "SPX"

    def test_stops_at_legend(self):
        rows = parse_log(LOG)
        assert all(r["symbol"] in ("NDX", "SPX") for r in rows)


class TestPnlStats:
    def test_win_rate_and_expectancy(self):
        rows = parse_log(LOG)
        s = pnl_stats(rows)
        assert s["trades"] == 3
        assert s["wins"] == 2 and s["losses"] == 1
        assert s["win_rate"] == round(2 / 3, 3)
        assert s["total_pnl"] == round(128 - 415 + 40, 2)  # -247
        assert s["expectancy_per_trade"] == round((128 - 415 + 40) / 3, 2)
        assert s["closed_by"] == {"target": 1, "stop-premium": 1, "time-exit": 1}

    def test_max_drawdown(self):
        # cumulative: 128, -287, -247 -> peak 128, trough -287 -> DD 415
        s = pnl_stats(parse_log(LOG))
        assert s["max_drawdown"] == 415.0

    def test_empty(self):
        assert pnl_stats([]) == {"trades": 0}

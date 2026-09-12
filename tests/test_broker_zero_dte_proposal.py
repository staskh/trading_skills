# ABOUTME: Tests for executing a previously saved 0DTE proposal.
# ABOUTME: Covers proposal lookup and the drift checks that refuse a stale trade.

import asyncio
import json

import pytest

from trading_skills.broker.zero_dte_proposal import (
    DEFAULT_MAX_CREDIT_DRIFT,
    DEFAULT_MAX_CUSHION_LOSS,
    ProposalError,
    check_drift,
    combo_ask_credit,
    execute_proposal,
    load_proposal,
    proposal_id_for,
)


def _candidate(short=7635.0, long_=7590.0, credit=1.0, spot=7675.0, right="P"):
    legs = [
        {"action": "sell", "right": right, "strike": short},
        {"action": "buy", "right": right, "strike": long_},
    ]
    return {
        "strategy": "bull_put",
        "legs": legs,
        "net_credit": credit,
        "combo_ask_credit": credit - 0.05,
        "width": abs(short - long_),
        "contracts": 3,
        "distance_to_short": abs(spot - short),
    }


def _condor(spot=7675.0):
    return {
        "strategy": "iron_condor",
        "legs": [
            {"action": "sell", "right": "C", "strike": 7700.0},
            {"action": "buy", "right": "C", "strike": 7730.0},
            {"action": "sell", "right": "P", "strike": 7640.0},
            {"action": "buy", "right": "P", "strike": 7610.0},
        ],
        "net_credit": 2.0,
        "combo_ask_credit": 1.9,
        "contracts": 2,
        "call_distance_to_short": 25.0,
        "put_distance_to_short": 35.0,
    }


class TestProposalId:
    """A proposal needs a stable handle that names the trade it describes."""

    def test_includes_symbol_expiry_and_type(self):
        pid = proposal_id_for("SPX", "20260912", "bull_put", "2026-09-12_142449")
        assert "SPX" in pid and "20260912" in pid and "bull_put" in pid

    def test_is_stable_for_the_same_run(self):
        args = ("SPX", "20260912", "bull_put", "2026-09-12_142449")
        assert proposal_id_for(*args) == proposal_id_for(*args)

    def test_differs_across_runs(self):
        a = proposal_id_for("SPX", "20260912", "bull_put", "2026-09-12_142449")
        b = proposal_id_for("SPX", "20260912", "bull_put", "2026-09-12_151520")
        assert a != b


class TestLoadProposal:
    def _write(self, tmp_path, name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload))
        return path

    def test_loads_by_explicit_path(self, tmp_path):
        payload = {"proposal_id": "SPX-20260912-bull_put-142449", "candidates": [_candidate()]}
        path = self._write(tmp_path, "run.json", payload)
        assert load_proposal(str(path))["proposal_id"] == payload["proposal_id"]

    def test_loads_by_id_from_search_dir(self, tmp_path):
        pid = "SPX-20260912-bull_put-142449"
        self._write(tmp_path, "SPX_0dte_x.json", {"proposal_id": pid, "candidates": [_candidate()]})
        assert load_proposal(pid, search_dir=tmp_path)["proposal_id"] == pid

    def test_unknown_id_raises(self, tmp_path):
        with pytest.raises(ProposalError, match="No saved proposal"):
            load_proposal("SPX-nope-bull_put-000000", search_dir=tmp_path)

    def test_proposal_without_candidates_raises(self, tmp_path):
        path = self._write(tmp_path, "run.json", {"proposal_id": "x", "candidates": []})
        with pytest.raises(ProposalError, match="no candidates"):
            load_proposal(str(path))

    def test_dry_run_marker_is_not_required_to_load(self, tmp_path):
        path = self._write(tmp_path, "r.json", {"proposal_id": "x", "candidates": [_candidate()]})
        assert load_proposal(str(path))["candidates"]


class TestCheckDrift:
    """A reviewed trade must still be the trade on offer, or it is refused."""

    def test_unchanged_market_passes(self):
        c = _candidate()
        ok = check_drift(c, fresh_credit=c["combo_ask_credit"], fresh_spot=7675.0)
        assert ok["ok"] is True
        assert ok["credit_drift"] == pytest.approx(0.0)

    def test_small_credit_slip_passes(self):
        c = _candidate(credit=1.0)  # combo_ask 0.95
        ok = check_drift(c, fresh_credit=0.90, fresh_spot=7675.0)
        assert ok["ok"] is True

    def test_large_credit_drop_is_refused(self):
        c = _candidate(credit=1.0)  # combo_ask 0.95
        res = check_drift(c, fresh_credit=0.50, fresh_spot=7675.0)
        assert res["ok"] is False
        assert "credit" in res["reason"].lower()

    def test_credit_improvement_is_never_refused(self):
        c = _candidate(credit=1.0)
        assert check_drift(c, fresh_credit=2.0, fresh_spot=7675.0)["ok"] is True

    def test_spot_moving_toward_the_short_strike_is_refused(self):
        """Cushion 40pts at proposal; a move to 10pts is most of it gone."""
        c = _candidate(short=7635.0, spot=7675.0)
        res = check_drift(c, fresh_credit=c["combo_ask_credit"], fresh_spot=7645.0)
        assert res["ok"] is False
        assert "cushion" in res["reason"].lower()

    def test_spot_moving_away_from_the_short_strike_passes(self):
        c = _candidate(short=7635.0, spot=7675.0)
        res = check_drift(c, fresh_credit=c["combo_ask_credit"], fresh_spot=7700.0)
        assert res["ok"] is True

    def test_condor_uses_the_nearest_short_leg(self):
        """The call side is the tighter cushion, so it governs."""
        c = _condor()
        res = check_drift(c, fresh_credit=c["combo_ask_credit"], fresh_spot=7690.0)
        assert res["ok"] is False
        assert "cushion" in res["reason"].lower()

    def test_tolerances_are_configurable(self):
        c = _candidate(credit=1.0)
        assert check_drift(c, fresh_credit=0.50, fresh_spot=7675.0, max_credit_drift=0.9)["ok"]

    def test_result_reports_the_measured_values(self):
        c = _candidate(credit=1.0, short=7635.0, spot=7675.0)
        res = check_drift(c, fresh_credit=0.90, fresh_spot=7665.0)
        assert res["proposed_credit"] == pytest.approx(0.95)
        assert res["fresh_credit"] == pytest.approx(0.90)
        assert res["proposed_cushion"] == pytest.approx(40.0)
        assert res["fresh_cushion"] == pytest.approx(30.0)

    def test_defaults_are_explicit_not_implicit(self):
        assert 0 < DEFAULT_MAX_CREDIT_DRIFT < 1
        assert 0 < DEFAULT_MAX_CUSHION_LOSS < 1

    def test_no_fresh_credit_is_refused(self):
        """A leg that will not quote cannot be validated, so it is not placed."""
        res = check_drift(_candidate(), fresh_credit=None, fresh_spot=7675.0)
        assert res["ok"] is False
        assert "quote" in res["reason"].lower()


class TestComboAskCredit:
    """Re-pricing the reviewed legs against a fresh quote."""

    QUOTES = {
        ("P", 7635.0): {"bid": 1.25, "ask": 1.30},
        ("P", 7590.0): {"bid": 0.35, "ask": 0.40},
    }

    def test_short_bid_minus_long_ask(self):
        legs = _candidate()["legs"]
        assert combo_ask_credit(legs, self.QUOTES) == pytest.approx(0.85)

    def test_missing_leg_returns_none(self):
        legs = _candidate(long_=7000.0)["legs"]
        assert combo_ask_credit(legs, self.QUOTES) is None

    def test_leg_without_a_side_returns_none(self):
        quotes = {**self.QUOTES, ("P", 7590.0): {"bid": 0.35, "ask": None}}
        assert combo_ask_credit(_candidate()["legs"], quotes) is None


class TestExecuteProposalGuards:
    """Guards that must refuse before any IB connection is opened."""

    def test_unknown_proposal_is_reported(self, tmp_path):
        res = asyncio.run(execute_proposal("nope-123", search_dir=tmp_path))
        assert res["success"] is False
        assert "No saved proposal" in res["error"]

    def test_pick_out_of_range_is_reported(self, tmp_path):
        path = tmp_path / "p.json"
        path.write_text(json.dumps({"proposal_id": "x", "candidates": [_candidate()]}))
        res = asyncio.run(execute_proposal(str(path), pick=4))
        assert res["success"] is False
        assert "out of range" in res["error"]

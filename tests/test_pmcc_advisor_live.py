# ABOUTME: Live IBKR integration test for PMCC advisor roll-candidate fetching.
# ABOUTME: Requires TWS/IB Gateway on port 7496 and NYSE open; deselected by default (manual).

import asyncio

import pytest

from trading_skills.broker.pmcc_advisor import get_pmcc_data

pytestmark = pytest.mark.manual


def test_roll_candidates_returned_for_cost():
    """With market open, the COST spread must yield roll candidates.

    Regression for issue #106: a single oversized asyncio.gather opened thousands of
    concurrent IBKR market-data subscriptions, exceeding the line limit, so every spread
    returned zero roll candidates. COST is the comment's named failing case (dense,
    high-priced chain). Per-spread fetching plus chunked, throttled quote batches keeps
    concurrent subscriptions small enough that quotes — and thus rolls — come back.
    """
    data = asyncio.run(get_pmcc_data(port=7496, symbols=["COST"]))
    spreads = data["spreads"]
    assert spreads, "COST PMCC spread not found in portfolio"
    assert spreads[0]["roll_candidates"], (
        "no roll candidates for COST — subscription overload likely returned"
    )

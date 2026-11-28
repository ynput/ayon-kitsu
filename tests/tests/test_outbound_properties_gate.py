"""Property test for gate decisions.

Validates: Requirements 2.3, 2.4, 2.8, 4.1, 4.8, 4.12
"""

# Feature: kitsu-two-way-sync, Property 2: A write is allowed only when
# enabled at creation and now

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    CATEGORY_TASK_STATUS,
    SKIP_CATEGORY_DISABLED,
    SKIP_DISABLED_AT_CREATION,
    SKIP_DISABLED_NO_HISTORY,
    SKIP_MASTER_DISABLED,
    SKIP_UNKNOWN_TOGGLE_STATE,
    SYNC_CATEGORIES,
)
from processor.outbound.gating import (
    gate_decision,
    toggles_at,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def _make_toggles(master: bool, category_enabled: bool, valid: bool = True):
    return {
        "valid": valid,
        "error": None if valid else "invalid settings",
        "master": master,
        "categories": {
            cat: (category_enabled if cat == CATEGORY_TASK_STATUS else False)
            for cat in SYNC_CATEGORIES
        },
        "conflict_policy": "kitsu_wins",
    }


@settings(max_examples=100, deadline=None)
@given(
    cat_creation=st.booleans(),
    master_creation=st.booleans(),
    cat_now=st.booleans(),
    master_now=st.booleans(),
    in_unknown_gap=st.booleans(),
    has_history=st.booleans(),
)
def test_gate_decision_allowed_iff_enabled_both(
    cat_creation,
    master_creation,
    cat_now,
    master_now,
    in_unknown_gap,
    has_history,
):
    """gate_decision allows write iff enabled at creation and now."""
    t_event = 1000.0
    category = CATEGORY_TASK_STATUS

    # Build gaps
    gaps = []
    if in_unknown_gap:
        gaps.append({
            "from": 900.0,
            "to": 1100.0,
            "unknown": True,
            "durationS": 200.0,
            "settingsChanges": 1,
        })

    # Build history
    history = []
    if has_history:
        history.append({
            "observedAt": 800.0,
            "toggles": _make_toggles(master_creation, cat_creation),
        })

    # Build now toggles
    now_toggles = _make_toggles(master_now, cat_now)

    at_creation = toggles_at(history, gaps, t_event)
    decision = gate_decision(category, at_creation, now_toggles)

    expected_allowed = (
        not in_unknown_gap
        and has_history
        and master_creation
        and cat_creation
        and master_now
        and cat_now
    )

    assert decision["allowed"] == expected_allowed
    if expected_allowed:
        assert decision["reason"] is None
    else:
        assert decision["reason"] is not None
        reason = decision["reason"]
        if in_unknown_gap:
            assert SKIP_UNKNOWN_TOGGLE_STATE in reason
        elif not has_history:
            expected = SKIP_DISABLED_NO_HISTORY.format(category=category)
            assert expected in reason
        elif not master_creation or not cat_creation:
            expected = SKIP_DISABLED_AT_CREATION.format(category=category)
            assert expected in reason
        else:
            # Disabled now
            assert (
                SKIP_CATEGORY_DISABLED.format(category=category) in reason
                or SKIP_MASTER_DISABLED in reason
            )

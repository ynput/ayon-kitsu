"""Property test for field decision table and job outcome.

Validates: Requirements 5.4, 9.1, 9.2, 9.4, 9.5, 9.6, 9.7
"""

# Feature: kitsu-two-way-sync, Property 7: Field decision table
# (equality and Conflict)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.conflict import (
    ACTION_CONFLICT_KEEP_KITSU,
    ACTION_CONFLICT_OVERWRITE,
    ACTION_SKIP_IN_SYNC,
    ACTION_WRITE,
    ACTION_WRITE_NO_PREVIOUS,
    OUTCOME_APPLIED,
    OUTCOME_CONFLICT,
    OUTCOME_FAILED,
    OUTCOME_SKIPPED_IN_SYNC,
    decide_field,
    job_outcome,
    values_equal,
)
from processor.outbound.constants import (
    CONFLICT_POLICIES,
    CONFLICT_POLICY_AYON_WINS,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

scalar_values = st.one_of(
    st.text(min_size=0, max_size=20),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
    st.none(),
)

assignee_values = st.lists(
    st.text(min_size=1, max_size=10), max_size=5
).map(lambda lst: lst + lst[:1])  # may contain duplicates


@settings(max_examples=100, deadline=None)
@given(
    field=st.sampled_from(["task_status_id", "fps", "assignees"]),
    val_a=scalar_values,
    val_b=scalar_values,
    val_c=scalar_values,
    has_previous=st.booleans(),
    policy=st.sampled_from(CONFLICT_POLICIES),
)
def test_field_decision_table_scalars(
    field, val_a, val_b, val_c, has_previous, policy
):
    """decide_field follows the decision table for scalar fields."""
    # Test cases:
    # 1. kitsu_current == new -> skip_in_sync
    # 2. kitsu_current != new, not has_previous -> write_no_previous
    # 3. kitsu_current != new, has_previous, kitsu_current == previous -> write
    # 4. kitsu_current != new, has_previous, kitsu_current != previous:
    #    conflict_keep_kitsu if kitsu_wins, conflict_overwrite if ayon_wins
    action = decide_field(
        field=field,
        previous=val_a,
        kitsu_current=val_b,
        new=val_c,
        has_previous=has_previous,
        policy=policy,
    )

    if values_equal(field, val_b, val_c):
        assert action["action"] == ACTION_SKIP_IN_SYNC
    elif not has_previous:
        assert action["action"] == ACTION_WRITE_NO_PREVIOUS
    elif values_equal(field, val_b, val_a):
        assert action["action"] == ACTION_WRITE
    else:
        if policy == CONFLICT_POLICY_AYON_WINS:
            assert action["action"] == ACTION_CONFLICT_OVERWRITE
        else:
            assert action["action"] == ACTION_CONFLICT_KEEP_KITSU


@settings(max_examples=100, deadline=None)
@given(
    assignees_prev=assignee_values,
    assignees_cur=assignee_values,
    assignees_new=assignee_values,
    has_previous=st.booleans(),
    policy=st.sampled_from(CONFLICT_POLICIES),
)
def test_field_decision_table_assignees(
    assignees_prev, assignees_cur, assignees_new, has_previous, policy
):
    """decide_field treats assignees as unordered sets."""
    action = decide_field(
        field="assignees",
        previous=assignees_prev,
        kitsu_current=assignees_cur,
        new=assignees_new,
        has_previous=has_previous,
        policy=policy,
    )

    set_cur = set(assignees_cur)
    set_new = set(assignees_new)
    set_prev = set(assignees_prev)

    if set_cur == set_new:
        assert action["action"] == ACTION_SKIP_IN_SYNC
    elif not has_previous:
        assert action["action"] == ACTION_WRITE_NO_PREVIOUS
    elif set_cur == set_prev:
        assert action["action"] == ACTION_WRITE
    else:
        if policy == CONFLICT_POLICY_AYON_WINS:
            assert action["action"] == ACTION_CONFLICT_OVERWRITE
        else:
            assert action["action"] == ACTION_CONFLICT_KEEP_KITSU


@settings(max_examples=100, deadline=None)
@given(
    actions=st.lists(
        st.sampled_from([
            ACTION_SKIP_IN_SYNC,
            ACTION_WRITE,
            ACTION_WRITE_NO_PREVIOUS,
            ACTION_CONFLICT_KEEP_KITSU,
            ACTION_CONFLICT_OVERWRITE,
        ]),
        min_size=1,
        max_size=10,
    ),
    has_error=st.booleans(),
)
def test_job_outcome_combines_decisions(actions, has_error):
    """job_outcome evaluates actions and errors correctly."""
    field_decisions = [
        {"action": act, "field": f"field_{i}"} for i, act in enumerate(actions)
    ]
    errors = ["some error"] if has_error else []

    outcome = job_outcome(field_decisions, errors=errors)

    if has_error:
        assert outcome == OUTCOME_FAILED
    elif all(a == ACTION_SKIP_IN_SYNC for a in actions):
        assert outcome == OUTCOME_SKIPPED_IN_SYNC
    elif any(
        a in (ACTION_CONFLICT_KEEP_KITSU, ACTION_CONFLICT_OVERWRITE)
        for a in actions
    ):
        assert outcome == OUTCOME_CONFLICT
    else:
        assert outcome == OUTCOME_APPLIED

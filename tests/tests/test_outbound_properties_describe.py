"""Property test for job descriptions and log lines.

Validates: Requirements 2.11, 4.3, 4.4, 12.4, 13.1, 13.2, 13.3
"""

# Feature: kitsu-two-way-sync, Property 25: Job description and log
# line content

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    CONFLICT_POLICY_AYON_WINS,
    CONFLICT_POLICY_KITSU_WINS,
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    DECISION_SKIPPED,
    DESCRIPTION_APPLIED,
    DESCRIPTION_CONFLICT,
    DESCRIPTION_FAILED,
    DESCRIPTION_SKIPPED,
    NONE_VALUE,
)
from processor.outbound.describe import (
    NO_KITSU_FIELD_WRITTEN,
    build_log_line,
    describe_job,
    log_level_for_decision,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@settings(max_examples=100, deadline=None)
@given(
    decision=st.sampled_from(
        [
            DECISION_APPLIED,
            DECISION_SKIPPED,
            DECISION_CONFLICT,
            DECISION_FAILED,
        ]
    ),
    project=st.text(min_size=1, max_size=15),
    entity_id=st.text(min_size=1, max_size=15),
    kitsu_id=st.one_of(st.text(min_size=1, max_size=15), st.none()),
    category=st.sampled_from(["task_status", "task_assignees"]),
    job_id=st.text(min_size=1, max_size=15),
)
def test_log_line_content_and_level(
    decision, project, entity_id, kitsu_id, category, job_id
):
    """Property 25: log line contains required fields and correct level."""
    details = {
        "project_name": project,
        "entity_id": entity_id,
        "kitsu_id": kitsu_id,
        "category": category,
        "job_id": job_id,
    }
    level, msg = build_log_line(decision, details)

    expected_level = log_level_for_decision(decision)
    assert level == expected_level

    assert f"[{decision}]" in msg
    assert f"project={project}" in msg
    assert f"entity={entity_id}" in msg
    assert f"category={category}" in msg
    assert f"Outbound job {job_id}" in msg
    if kitsu_id:
        assert f"kitsu_id={kitsu_id}" in msg
    else:
        assert f"kitsu_id={NONE_VALUE}" in msg


@settings(max_examples=100, deadline=None)
@given(
    field_name=st.text(min_size=1, max_size=10),
    before=st.one_of(st.text(max_size=10), st.none()),
    sent=st.one_of(st.text(max_size=10), st.none()),
    kitsu_id=st.text(min_size=1, max_size=10),
)
def test_applied_description_formatting(field_name, before, sent, kitsu_id):
    """Property 25: applied description starts with prefix and lists writes."""
    details = {
        "kitsu_id": kitsu_id,
        "writes": [{"field": field_name, "before": before, "sent": sent}],
    }
    desc = describe_job(DECISION_APPLIED, details)
    assert desc.startswith(DESCRIPTION_APPLIED)
    assert field_name in desc
    assert "before:" in desc
    assert "sent:" in desc


@settings(max_examples=100, deadline=None)
@given(
    event_id=st.text(min_size=1, max_size=10),
    project_name=st.text(min_size=1, max_size=10),
    category=st.sampled_from(["task_status", "entity_attributes"]),
)
def test_gated_skip_description(event_id, project_name, category):
    """Property 25: gated skip includes event, project, category, no-write."""
    details = {
        "gated": True,
        "reason": f"{category} disabled at event creation time",
        "event_id": event_id,
        "project_name": project_name,
        "category": category,
    }
    desc = describe_job(DECISION_SKIPPED, details)
    assert desc.startswith(DESCRIPTION_SKIPPED)
    assert f"event={event_id}" in desc
    assert f"project={project_name}" in desc
    assert f"category={category}" in desc
    assert NO_KITSU_FIELD_WRITTEN.lower() in desc.lower()


@settings(max_examples=100, deadline=None)
@given(
    policy=st.sampled_from(
        [CONFLICT_POLICY_KITSU_WINS, CONFLICT_POLICY_AYON_WINS]
    ),
    field_name=st.text(min_size=1, max_size=10),
    prev_val=st.text(max_size=10),
    cur_val=st.text(max_size=10),
    new_val=st.text(max_size=10),
)
def test_conflict_description(
    policy, field_name, prev_val, cur_val, new_val
):
    """Property 25: conflict description states policy outcome and writes."""
    details = {
        "policy": policy,
        "field": field_name,
        "previous": prev_val,
        "kitsu_current": cur_val,
        "new": new_val,
    }
    desc = describe_job(DECISION_CONFLICT, details)
    assert desc.startswith(DESCRIPTION_CONFLICT)
    if policy == CONFLICT_POLICY_KITSU_WINS:
        assert NO_KITSU_FIELD_WRITTEN.lower() in desc.lower()
    else:
        assert NO_KITSU_FIELD_WRITTEN.lower() not in desc.lower()


@settings(max_examples=100, deadline=None)
@given(
    is_retryable=st.booleans(),
    attempt=st.integers(min_value=1, max_value=4),
    error_str=st.text(min_size=1, max_size=20),
)
def test_failed_description(is_retryable, attempt, error_str):
    """Property 25: failed description starts with Failed: and no-write."""
    details = {
        "retryable": is_retryable,
        "attempt": attempt,
        "error": error_str,
        "entity_id": "ent-1",
        "category": "task_status",
    }
    desc = describe_job(DECISION_FAILED, details)
    assert desc.startswith(DESCRIPTION_FAILED)
    assert NO_KITSU_FIELD_WRITTEN.lower() in desc.lower()

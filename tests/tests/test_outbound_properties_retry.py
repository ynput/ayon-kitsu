"""Property test for retry policy.

Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.6, 10.9
"""

# Feature: kitsu-two-way-sync, Property 20: Retry policy

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    DECISION_FAILED,
    MAX_ATTEMPTS,
    RETRY_DEADLINE_S,
    RETRY_DELAY_S,
)
from processor.outbound.describe import describe_job
from processor.outbound.retry import (
    FINAL_RETRIES_VALUE,
    RETRYABLE_KINDS,
    retry_decision,
    retry_due,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

ALL_ERROR_KINDS = list(RETRYABLE_KINDS) + [
    "permission",
    "not_found",
    "rejected",
    "identity",
    "mapping",
    "invalid_frame_range",
    "internal",
]


@settings(max_examples=100, deadline=None)
@given(
    error_sequence=st.lists(
        st.sampled_from(ALL_ERROR_KINDS), min_size=1, max_size=10
    ),
    restart_after=st.integers(min_value=0, max_value=5),
)
def test_retry_policy_simulation(error_sequence, restart_after):
    """retry_decision enforces max attempts and classifies errors correctly."""
    attempt = 1
    total_attempts = 0
    is_final = False

    for idx, error_kind in enumerate(error_sequence):
        # Simulate processor restart: job state saved to summary.attempt
        if idx == restart_after:
            persisted_attempt = attempt
            # Processor restarts, restored attempt matches persisted
            attempt = persisted_attempt

        total_attempts += 1
        decision = retry_decision(error_kind, attempt)

        if decision["final"]:
            is_final = True
            assert decision["retries_value"] == FINAL_RETRIES_VALUE
            assert decision["not_before_s"] is None
            assert decision["not_after_s"] is None
            if error_kind in RETRYABLE_KINDS:
                assert attempt >= MAX_ATTEMPTS
            else:
                assert error_kind not in RETRYABLE_KINDS

            desc = describe_job(
                DECISION_FAILED,
                {
                    "retryable": False,
                    "attempt": attempt,
                    "error": error_kind,
                    "category": "task_status",
                },
            )
            assert desc.startswith("Failed:")
            assert "no kitsu field was written" in desc.lower()
            break
        else:
            assert error_kind in RETRYABLE_KINDS
            assert attempt < MAX_ATTEMPTS
            assert decision["retries_value"] is None
            assert decision["not_before_s"] == RETRY_DELAY_S
            assert decision["not_after_s"] == RETRY_DEADLINE_S

            desc = describe_job(
                DECISION_FAILED,
                {
                    "retryable": True,
                    "attempt": attempt,
                    "error_kind": error_kind,
                },
            )
            assert desc.startswith("Failed:")
            assert f"attempt {attempt}/4" in desc
            assert "no kitsu field was written" in desc.lower()

            attempt += 1

    assert total_attempts <= MAX_ATTEMPTS
    if is_final:
        assert total_attempts <= MAX_ATTEMPTS
    else:
        assert all(err in RETRYABLE_KINDS for err in error_sequence)
        assert total_attempts < MAX_ATTEMPTS


@settings(max_examples=100, deadline=None)
@given(
    last_failed_at=st.floats(min_value=1000.0, max_value=50000.0),
    elapsed=st.floats(min_value=0.0, max_value=120.0),
    excluded_s=st.floats(min_value=0.0, max_value=60.0),
)
def test_retry_due_bounds(last_failed_at, elapsed, excluded_s):
    """retry_due obeys 10s and 60s bounds minus excluded time."""
    now = last_failed_at + elapsed
    res = retry_due(last_failed_at, now, excluded_s)

    net_elapsed = now - last_failed_at - excluded_s
    expected_due = net_elapsed >= RETRY_DELAY_S
    expected_late = net_elapsed > RETRY_DEADLINE_S

    assert res["due"] == expected_due
    assert res["late"] == expected_late
    if res["late"]:
        assert res["due"] is True

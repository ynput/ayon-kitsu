"""Property test for loop guard suppression.

Validates: Requirements 5.9
"""

# Feature: kitsu-two-way-sync, Property 10: Loop guard suppression

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    DECISION_SKIPPED,
    LOOP_GUARD_MAX_WRITES,
    LOOP_GUARD_SUPPRESS_S,
    LOOP_GUARD_WINDOW_S,
    SKIP_LOOP_SUSPECTED,
)
from processor.outbound.loop_guard import loop_guard_check

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


class ReferenceLoopGuard:
    """Independent reference model for loop guard suppression."""

    def __init__(self):
        self.allowed_writes = []
        self.suppressed_until = None

    def check(self, t: float) -> bool:
        if self.suppressed_until is not None and t < self.suppressed_until:
            return False

        self.suppressed_until = None
        # Writes within window [t - 60, t]
        recent = [
            w for w in self.allowed_writes if w >= t - LOOP_GUARD_WINDOW_S
        ]
        self.allowed_writes.append(t)
        if len(recent) + 1 >= LOOP_GUARD_MAX_WRITES:
            self.suppressed_until = t + LOOP_GUARD_SUPPRESS_S
        return True


@settings(max_examples=100, deadline=None)
@given(
    deltas=st.lists(
        st.floats(
            min_value=0.0,
            max_value=120.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=1,
        max_size=50,
    ),
    start_time=st.floats(
        min_value=1000.0,
        max_value=100000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_loop_guard_agrees_with_reference_model(deltas, start_time):
    """loop_guard_check agrees with the reference model across write times."""
    # Build monotonically increasing timestamps
    timestamps = []
    current = start_time
    for d in deltas:
        current += d
        timestamps.append(current)

    ref = ReferenceLoopGuard()
    write_times = []
    suppressed_until = None
    all_allowed = []

    for t in timestamps:
        ref_allowed = ref.check(t)
        result = loop_guard_check(write_times, suppressed_until, t)

        assert result["allowed"] == ref_allowed
        write_times = result["write_times"]
        suppressed_until = result["suppressed_until"]

        if result["allowed"]:
            all_allowed.append(t)
            assert result["decision"] is None
            assert result["reason"] is None
        else:
            assert result["decision"] == DECISION_SKIPPED
            assert result["reason"] == SKIP_LOOP_SUSPECTED

    # Verify invariant: no 60 s window contains more than 3 allowed writes
    for i, t in enumerate(all_allowed):
        window_count = sum(
            1 for w in all_allowed if t - LOOP_GUARD_WINDOW_S <= w <= t
        )
        assert window_count <= LOOP_GUARD_MAX_WRITES

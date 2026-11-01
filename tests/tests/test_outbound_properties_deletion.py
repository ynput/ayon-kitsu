"""Property test for deletion guard (Property 24).

Validates: Requirements 12.3
"""

# Feature: kitsu-two-way-sync, Property 24: Deletion guard (Slice 3)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.planning import plan_deletion

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@settings(max_examples=200, deadline=None)
@given(
    comments=st.integers(min_value=0, max_value=100),
    previews=st.integers(min_value=0, max_value=100),
    children=st.integers(min_value=0, max_value=100),
    use_dict=st.booleans(),
)
def test_deletion_guard_property(comments, previews, children, use_dict):
    """Property 24: deletion allowed iff all counts are zero.

    When blocked, reason starts with 'Skipped:' and lists every non-zero
    count by item type. Zero counts are not listed.
    """
    if use_dict:
        counts = {
            "comments": comments,
            "previews": previews,
            "children": children,
        }
        plan = plan_deletion(counts=counts)
    else:
        plan = plan_deletion(
            comments=comments,
            previews=previews,
            children=children,
        )

    all_zero = (comments == 0 and previews == 0 and children == 0)

    if all_zero:
        assert plan["allowed"] is True
        assert plan["action"] == "delete"
        assert plan["reason"] is None
    else:
        assert plan["allowed"] is False
        assert plan["action"] == "skip"
        assert plan["reason"].startswith("Skipped:")

        # Every non-zero count is listed
        if comments > 0:
            assert f"{comments} comments" in plan["reason"]
        else:
            assert "comments" not in plan["reason"]

        if previews > 0:
            assert f"{previews} previews" in plan["reason"]
        else:
            assert "previews" not in plan["reason"]

        if children > 0:
            assert f"{children} children" in plan["reason"]
        else:
            assert "children" not in plan["reason"]


def test_deletion_unit_examples():
    """Unit tests for deletion planning edge cases."""
    # All zero counts -> allowed
    p1 = plan_deletion(comments=0, previews=0, children=0)
    assert p1["allowed"] is True
    assert p1["action"] == "delete"
    assert p1["reason"] is None

    # Empty dict -> allowed
    p2 = plan_deletion(counts={})
    assert p2["allowed"] is True
    assert p2["action"] == "delete"

    # Only 1 comment -> blocked
    p3 = plan_deletion(comments=1, previews=0, children=0)
    assert p3["allowed"] is False
    assert p3["action"] == "skip"
    assert p3["reason"] == "Skipped: entity has 1 comments"

    # Only 3 previews -> blocked
    p4 = plan_deletion(comments=0, previews=3, children=0)
    assert p4["allowed"] is False
    assert p4["reason"] == "Skipped: entity has 3 previews"

    # Multiple blocking items -> sorted item list
    p5 = plan_deletion(comments=2, previews=1, children=5)
    assert p5["allowed"] is False
    expected_msg = (
        "Skipped: entity has 5 children, 2 comments, 1 previews"
    )
    assert p5["reason"] == expected_msg

"""Property test for rename target name (Property 23).

Validates: Requirements 12.1
"""

# Feature: kitsu-two-way-sync, Property 23: Rename target name (Slice 3)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.planning import plan_rename

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@settings(max_examples=200, deadline=None)
@given(
    name=st.text(min_size=1, max_size=50),
    label=st.one_of(
        st.none(),
        st.just(""),
        st.just("   "),
        st.text(min_size=0, max_size=50),
    ),
)
def test_rename_target_name_property(name, label):
    """Property 23: Kitsu name is label if non-empty, name otherwise.

    Changes no Kitsu field other than 'name'.
    """
    clean_label = label.strip() if isinstance(label, str) else None
    expected_target = clean_label if clean_label else name

    plan = plan_rename(name=name, label=label)

    # 1. Target name matches expected
    assert plan["target_name"] == expected_target

    # 2. Only 'name' field is planned for write
    assert plan["fields"] == {"name": expected_target}
    assert set(plan["fields"].keys()) == {"name"}


def test_rename_unit_examples():
    """Unit tests for rename planning edge cases."""
    # Label is None -> uses name
    p1 = plan_rename(name="sh010", label=None)
    assert p1["target_name"] == "sh010"
    assert p1["fields"] == {"name": "sh010"}

    # Label is empty string -> uses name
    p2 = plan_rename(name="sh010", label="")
    assert p2["target_name"] == "sh010"
    assert p2["fields"] == {"name": "sh010"}

    # Label is only whitespace -> uses name
    p3 = plan_rename(name="sh010", label="   \t\n")
    assert p3["target_name"] == "sh010"
    assert p3["fields"] == {"name": "sh010"}

    # Label is non-empty -> uses label
    p4 = plan_rename(name="sh010", label="Shot 010")
    assert p4["target_name"] == "Shot 010"
    assert p4["fields"] == {"name": "Shot 010"}

    # Padded label is stripped
    p5 = plan_rename(name="sh010", label="  Shot 010  ")
    assert p5["target_name"] == "Shot 010"
    assert p5["fields"] == {"name": "Shot 010"}

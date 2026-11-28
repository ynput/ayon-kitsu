"""Property test for status mapping round trip.

Validates: Requirements 6.5
"""

# Feature: kitsu-two-way-sync, Property 12: Status mapping round trip

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.mapping import kitsu_status_to_ayon, map_status

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@settings(max_examples=100, deadline=None)
@given(
    target_id=st.uuids().map(str),
    target_name=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=50,
    ),
    other_names=st.lists(
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=1,
            max_size=50,
        ),
        max_size=20,
    ),
)
def test_status_mapping_round_trip(target_id, target_name, other_names):
    """Mapping unique status to AYON and back returns original id."""
    target_status = {
        "id": target_id,
        "name": target_name,
        "archived": False,
    }

    # Ensure other statuses either have a different name or are archived
    other_statuses = []
    for idx, name in enumerate(other_names):
        if name == target_name:
            # If name matches target, it must be archived to keep target unique
            other_statuses.append({
                "id": f"archived-{idx}",
                "name": name,
                "archived": True,
            })
        else:
            other_statuses.append({
                "id": f"other-{idx}",
                "name": name,
                "archived": False,
            })

    all_statuses = [target_status] + other_statuses

    ayon_status_name = kitsu_status_to_ayon(target_status)
    assert ayon_status_name == target_name

    res = map_status(ayon_status_name, all_statuses)
    assert res["ok"] is True
    assert res["status"]["id"] == target_id

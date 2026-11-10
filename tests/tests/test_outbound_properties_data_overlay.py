"""Property test for data overlay preserving unrelated keys (Property 18).

Validates: Requirements 8.4
"""

# Feature: kitsu-two-way-sync, Property 18: Data overlay (Slice 2)

import copy
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.planning import merge_kitsu_data

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

st_val = st.one_of(
    st.integers(min_value=-1000, max_value=10000),
    st.text(min_size=0, max_size=30),
    st.floats(min_value=-100.0, max_value=100.0, allow_nan=False),
    st.booleans(),
    st.none(),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(
        st.text(min_size=1, max_size=10), st.integers(), max_size=2
    ),
)


@settings(max_examples=100, deadline=None)
@given(
    original_data=st.dictionaries(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                whitelist_characters="_",
            ),
            min_size=1,
            max_size=15,
        ),
        st_val,
        max_size=10,
    ),
    planned_data_keys=st.dictionaries(
        st.sampled_from(
            ["frame_in", "frame_out", "fps", "resolution", "custom"]
        ),
        st_val,
        max_size=5,
    ),
    top_level_fields=st.dictionaries(
        st.sampled_from(["nb_frames", "description", "other_top_field"]),
        st_val,
        max_size=3,
    ),
)
def test_merge_kitsu_data_properties(
    original_data, planned_data_keys, top_level_fields
):
    """Property 18: data overlay updates planned keys, preserves unrelated."""
    # Prefix planned data keys with "data."
    planned_fields = {f"data.{k}": v for k, v in planned_data_keys.items()}
    # Add top-level fields (which must be ignored by merge_kitsu_data)
    planned_fields.update(top_level_fields)

    # Copy before call to test non-mutation
    orig_copy = copy.deepcopy(original_data)
    plan_copy = copy.deepcopy(planned_fields)

    merged = merge_kitsu_data(original_data, planned_fields)

    # Assert non-mutation
    assert original_data == orig_copy
    assert planned_fields == plan_copy

    # 1. Fresh dictionary returned
    assert merged is not original_data

    # 2. Top level fields never leak into merged data
    for top_k in top_level_fields:
        if top_k not in original_data and top_k not in planned_data_keys:
            assert top_k not in merged

    # 3. Every planned data key has the planned value
    for k, v in planned_data_keys.items():
        assert merged[k] == v

    # 4. Every original key not in planned_data_keys keeps its original value
    for orig_k, orig_v in original_data.items():
        if orig_k not in planned_data_keys:
            assert merged[orig_k] == orig_v

    # 5. No original keys are dropped
    assert set(original_data.keys()).issubset(set(merged.keys()))


def test_merge_kitsu_data_none_and_empty():
    """Handles None or empty inputs gracefully."""
    assert merge_kitsu_data(None, {}) == {}
    assert merge_kitsu_data({}, {}) == {}
    assert merge_kitsu_data(None, {"data.fps": 24.0}) == {"fps": 24.0}
    assert merge_kitsu_data({"keep": 1}, {}) == {"keep": 1}

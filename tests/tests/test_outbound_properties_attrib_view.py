"""Property test for Processor attribute view agreement with Inbound parsing.

Validates: Requirements 5.3, 5.4
"""

# Feature: kitsu-two-way-sync, Property 8: Processor attribute view agrees

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from attrib_parsing import end_frame_from_kitsu, parse_attrib
from processor.outbound.mapping import kitsu_attrib_view

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def inbound_oracle(
    kitsu_entity: dict, fallback_frame_start: int | None = None
) -> dict:
    """Real Inbound parsing pipeline from push.py and attrib_parsing."""
    if not isinstance(kitsu_entity, dict):
        return {}
    raw_data = kitsu_entity.get("data")
    data = dict(raw_data) if isinstance(raw_data, dict) else {}
    if "description" in kitsu_entity:
        data["description"] = kitsu_entity["description"] or ""
    data["frame_out"] = end_frame_from_kitsu(
        kitsu_entity, fallback_frame_start
    )
    return parse_attrib(data)


# Strategy for generating Kitsu entity dicts with arbitrary data fields
st_field_val = st.one_of(
    st.integers(min_value=-1000, max_value=200000),
    st.floats(min_value=-1000.0, max_value=200000.0),
    st.text(min_size=0, max_size=30),
    st.booleans(),
    st.lists(st.integers(), max_size=2),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
    st.none(),
)

st_data_dict = st.fixed_dictionaries(
    {},
    optional={
        "fps": st_field_val,
        "frame_in": st_field_val,
        "frame_out": st_field_val,
        "resolution": st.one_of(
            st.tuples(
                st.integers(min_value=1, max_value=8192),
                st.integers(min_value=1, max_value=8192),
            ).map(lambda p: f"{p[0]}x{p[1]}"),
            st_field_val,
        ),
        "description": st.one_of(
            st.text(min_size=0, max_size=50), st.none()
        ),
        "start_date": st.one_of(
            st.text(min_size=0, max_size=20), st_field_val
        ),
        "end_date": st.one_of(
            st.text(min_size=0, max_size=20), st_field_val
        ),
        "extra_key": st.text(min_size=0, max_size=20),
    },
)


@settings(max_examples=100, deadline=None)
@given(
    data=st.one_of(st_data_dict, st.none(), st.just("invalid-data-type")),
    nb_frames=st.one_of(
        st.integers(min_value=-10, max_value=1000),
        st.none(),
        st.just("not-an-int"),
    ),
    entity_desc=st.one_of(
        st.text(min_size=0, max_size=50),
        st.none(),
    ),
    fallback_start=st.one_of(
        st.integers(min_value=0, max_value=10000),
        st.none(),
    ),
)
def test_kitsu_attrib_view_agrees_with_inbound(
    data, nb_frames, entity_desc, fallback_start
):
    """Property 8: kitsu_attrib_view equals real Inbound parsing pipeline."""
    entity = {}
    if data != "invalid-data-type":
        entity["data"] = data
    else:
        entity["data"] = "invalid"

    if nb_frames is not None:
        entity["nb_frames"] = nb_frames

    if entity_desc is not None:
        entity["description"] = entity_desc

    try:
        oracle_res = inbound_oracle(entity, fallback_start)
        oracle_exc = None
    except Exception as exc:
        oracle_res = None
        oracle_exc = type(exc)

    try:
        view_res = kitsu_attrib_view(entity, fallback_start)
        view_exc = None
    except Exception as exc:
        view_res = None
        view_exc = type(exc)

    assert view_exc == oracle_exc
    if oracle_exc is None:
        assert view_res.keys() == oracle_res.keys()
        for k in view_res:
            v_val = view_res[k]
            o_val = oracle_res[k]
            if isinstance(v_val, float) and isinstance(o_val, float):
                if math.isnan(v_val) and math.isnan(o_val):
                    continue
            assert v_val == o_val

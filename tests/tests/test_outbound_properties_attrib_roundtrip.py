"""Property test for attribute round trip (Property 19).

Validates: Requirements 8.7
"""

# Feature: kitsu-two-way-sync, Property 19: Attribute round trip (Slice 2)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from attrib_parsing import end_frame_from_kitsu, parse_attrib
from processor.outbound.mapping import ayon_attrib_to_kitsu

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@settings(max_examples=100, deadline=None)
@given(
    frame_start=st.integers(min_value=-1_000_000, max_value=10_000_000),
    frame_delta=st.integers(min_value=0, max_value=10_000_000),
    fps=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False),
    res_w=st.integers(min_value=1, max_value=32768),
    res_h=st.integers(min_value=1, max_value=32768),
    description=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=1,
        max_size=10_000,
    ),
)
def test_attribute_roundtrip_property(
    frame_start, frame_delta, fps, res_w, res_h, description
):
    """Property 19: converting to Kitsu and parsing back returns originals."""
    frame_end = min(frame_start + frame_delta, 10_000_000)

    ayon_attrib = {
        "frameStart": frame_start,
        "frameEnd": frame_end,
        "fps": fps,
        "resolutionWidth": res_w,
        "resolutionHeight": res_h,
        "description": description,
    }

    # 1. Outbound conversion
    kitsu_fields = ayon_attrib_to_kitsu(ayon_attrib)

    # 2. Assemble Zou entity dictionary
    entity = {"data": {}}
    for k, v in kitsu_fields.items():
        if k.startswith("data."):
            entity["data"][k[5:]] = v
        else:
            entity[k] = v

    # 3. Inbound parsing pipeline (push.py + attrib_parsing)
    data = dict(entity.get("data", {}))
    if entity.get("description"):
        data["description"] = entity["description"]
    data["frame_out"] = end_frame_from_kitsu(entity)
    back_attrib = parse_attrib(data)

    # 4. Assert round-trip equality (exact float equality for fps)
    assert back_attrib["frameStart"] == ayon_attrib["frameStart"]
    assert back_attrib["frameEnd"] == ayon_attrib["frameEnd"]
    assert back_attrib["fps"] == ayon_attrib["fps"]
    assert back_attrib["resolutionWidth"] == ayon_attrib["resolutionWidth"]
    assert back_attrib["resolutionHeight"] == ayon_attrib["resolutionHeight"]
    assert back_attrib["description"] == ayon_attrib["description"]


@pytest.mark.parametrize(
    "start,end,fps,w,h,desc",
    [
        (0, 0, 1.0, 1, 1, "boundary minimums"),
        (0, 10_000_000, 1000.0, 32768, 32768, "boundary maximums"),
        (1001, 1100, 23.976, 1920, 1080, "typical film shot"),
        (1, 100, 24.0, 1920, 1080, "A" * 10_000),
    ],
)
def test_attribute_roundtrip_boundaries(start, end, fps, w, h, desc):
    """Explicit boundary value tests matching Requirement 8.7."""
    ayon_attrib = {
        "frameStart": start,
        "frameEnd": end,
        "fps": fps,
        "resolutionWidth": w,
        "resolutionHeight": h,
        "description": desc,
    }
    kitsu_fields = ayon_attrib_to_kitsu(ayon_attrib)
    entity = {"data": {}}
    for k, v in kitsu_fields.items():
        if k.startswith("data."):
            entity["data"][k[5:]] = v
        else:
            entity[k] = v

    data = dict(entity.get("data", {}))
    if entity.get("description"):
        data["description"] = entity["description"]
    data["frame_out"] = end_frame_from_kitsu(entity)
    back_attrib = parse_attrib(data)

    assert back_attrib["frameStart"] == start
    assert back_attrib["frameEnd"] == end
    assert back_attrib["fps"] == fps
    assert back_attrib["resolutionWidth"] == w
    assert back_attrib["resolutionHeight"] == h
    assert back_attrib["description"] == desc

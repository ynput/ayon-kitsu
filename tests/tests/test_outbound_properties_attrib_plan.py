"""Property test for attribute write plan (Property 17).

Validates: Requirements 8.1, 8.2, 8.3, 8.5, 8.6, 8.8, 8.9
"""

# Feature: kitsu-two-way-sync, Property 17: Attribute write plan (Slice 2)

import copy
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.mapping import MAPPED_ATTRIBUTES
from processor.outbound.planning import plan_attribute_write

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

ALL_MAPPED = sorted(MAPPED_ATTRIBUTES)


@settings(max_examples=100, deadline=None)
@given(
    changed_keys=st.sets(
        st.sampled_from(ALL_MAPPED + ["unmapped_foo", "unmapped_bar"]),
        max_size=6,
    ),
    own_keys=st.sets(
        st.sampled_from(ALL_MAPPED),
        max_size=6,
    ),
    frame_start=st.one_of(
        st.integers(min_value=-500, max_value=5000), st.none()
    ),
    frame_end=st.one_of(
        st.integers(min_value=-500, max_value=5000), st.none()
    ),
    res_w=st.one_of(st.integers(min_value=1, max_value=4096), st.none()),
    res_h=st.one_of(st.integers(min_value=1, max_value=4096), st.none()),
    fps_val=st.one_of(
        st.floats(min_value=1.0, max_value=120.0, allow_nan=False), st.none()
    ),
    desc_val=st.one_of(st.text(min_size=0, max_size=40), st.none()),
)
def test_plan_attribute_write_properties(
    changed_keys,
    own_keys,
    frame_start,
    frame_end,
    res_w,
    res_h,
    fps_val,
    desc_val,
):
    """Property 17: planner obeys mapped, owned, pair, error, and skip."""
    effective = {}
    if frame_start is not None:
        effective["frameStart"] = frame_start
    if frame_end is not None:
        effective["frameEnd"] = frame_end
    if res_w is not None:
        effective["resolutionWidth"] = res_w
    if res_h is not None:
        effective["resolutionHeight"] = res_h
    if fps_val is not None:
        effective["fps"] = fps_val
    if desc_val is not None:
        effective["description"] = desc_val

    changed = {k: effective.get(k) for k in changed_keys}
    own_attrib = list(own_keys)

    # Copy before call to verify non-mutation
    changed_copy = copy.deepcopy(changed)
    effective_copy = copy.deepcopy(effective)
    own_copy = list(own_attrib)

    plan = plan_attribute_write(changed, effective, own_attrib)

    # Assert non-mutation
    assert changed == changed_copy
    assert effective == effective_copy
    assert own_attrib == own_copy

    fields = plan["fields"]
    skipped = plan["skipped"]
    errors = plan["errors"]

    # 1. Unmapped attributes are skipped
    for k in changed_keys:
        if k not in ALL_MAPPED:
            assert skipped.get(k) == "unmapped"

    # 2. Changed attributes not in own_attrib are skipped as inherited
    for k in changed_keys:
        if k in ALL_MAPPED and k not in own_keys:
            assert skipped.get(k) == "inherited"

    # 3. Invalid frame range check applies when planning a frame-range write
    fs_in_changed_own = (
        "frameStart" in changed_keys and "frameStart" in own_keys
    )
    fe_in_changed_own = (
        "frameEnd" in changed_keys and "frameEnd" in own_keys
    )
    fs_inh = "frameStart" in changed_keys and "frameStart" not in own_keys
    fe_inh = "frameEnd" in changed_keys and "frameEnd" not in own_keys
    frame_write_attempted = (fs_in_changed_own and not fe_inh) or (
        fe_in_changed_own and not fs_inh
    )
    invalid_range = (
        frame_write_attempted
        and frame_start is not None
        and frame_end is not None
        and frame_end < frame_start
    )
    if invalid_range:
        assert any("invalid frame range" in err for err in errors)
        assert "data.frame_in" not in fields
        assert "data.frame_out" not in fields
        assert "nb_frames" not in fields
    else:
        assert not any("invalid frame range" in err for err in errors)

    # 4. fps handling
    if "fps" in changed_keys and "fps" in own_keys:
        if fps_val is not None:
            assert fields["data.fps"] == float(fps_val)
        else:
            assert skipped.get("fps") == "missing value"
            assert "data.fps" not in fields
    else:
        assert "data.fps" not in fields

    # 5. description handling (including empty string "")
    if "description" in changed_keys and "description" in own_keys:
        if desc_val is not None:
            assert fields["description"] == desc_val
        else:
            assert skipped.get("description") == "missing value"
            assert "description" not in fields
    else:
        assert "description" not in fields

    # 6. Frame range handling

    if fs_in_changed_own or fe_in_changed_own:
        if fs_in_changed_own and fe_inh:
            assert (
                skipped.get("frameStart")
                == "counterpart changed and inherited"
            )
            assert "data.frame_in" not in fields
            assert "data.frame_out" not in fields
            assert "nb_frames" not in fields
        elif fe_in_changed_own and fs_inh:
            assert (
                skipped.get("frameEnd")
                == "counterpart changed and inherited"
            )
            assert "data.frame_in" not in fields
            assert "data.frame_out" not in fields
            assert "nb_frames" not in fields
        elif invalid_range:
            assert "data.frame_in" not in fields
            assert "data.frame_out" not in fields
            assert "nb_frames" not in fields
        elif frame_start is None or frame_end is None:
            if fs_in_changed_own:
                assert skipped.get("frameStart") == "missing value"
            if fe_in_changed_own:
                assert skipped.get("frameEnd") == "missing value"
            assert "data.frame_in" not in fields
            assert "data.frame_out" not in fields
            assert "nb_frames" not in fields
        else:
            assert fields["data.frame_in"] == frame_start
            assert fields["data.frame_out"] == frame_end
            assert fields["nb_frames"] == frame_end - frame_start + 1
    else:
        assert "data.frame_in" not in fields
        assert "data.frame_out" not in fields
        assert "nb_frames" not in fields

    # 7. Resolution handling
    rw_in_changed_own = (
        "resolutionWidth" in changed_keys and "resolutionWidth" in own_keys
    )
    rh_in_changed_own = (
        "resolutionHeight" in changed_keys and "resolutionHeight" in own_keys
    )
    rw_inh = (
        "resolutionWidth" in changed_keys and "resolutionWidth" not in own_keys
    )
    rh_inh = (
        "resolutionHeight" in changed_keys
        and "resolutionHeight" not in own_keys
    )

    if rw_in_changed_own or rh_in_changed_own:
        if rw_in_changed_own and rh_inh:
            assert (
                skipped.get("resolutionWidth")
                == "counterpart changed and inherited"
            )
            assert "data.resolution" not in fields
        elif rh_in_changed_own and rw_inh:
            assert (
                skipped.get("resolutionHeight")
                == "counterpart changed and inherited"
            )
            assert "data.resolution" not in fields
        elif res_w is None or res_h is None:
            if rw_in_changed_own:
                assert skipped.get("resolutionWidth") == "missing value"
            if rh_in_changed_own:
                assert skipped.get("resolutionHeight") == "missing value"
            assert "data.resolution" not in fields
        else:
            assert fields["data.resolution"] == f"{res_w}x{res_h}"
    else:
        assert "data.resolution" not in fields


def test_invalid_frame_range_preserves_other_planned_fields():
    """Requirement 8.3: invalid frame range keeps other planned fields."""
    changed = {
        "frameStart": 1050,
        "frameEnd": 1000,
        "fps": 25.0,
        "description": "Valid update",
    }
    effective = {
        "frameStart": 1050,
        "frameEnd": 1000,
        "fps": 25.0,
        "description": "Valid update",
    }
    own = ["frameStart", "frameEnd", "fps", "description"]

    plan = plan_attribute_write(changed, effective, own)

    assert "data.frame_in" not in plan["fields"]
    assert "data.frame_out" not in plan["fields"]
    assert "nb_frames" not in plan["fields"]
    assert len(plan["errors"]) == 1
    expected_err = (
        "invalid frame range: frameEnd (1000) < frameStart (1050)"
    )
    assert expected_err in plan["errors"][0]

    # Other planned fields are strictly preserved
    assert plan["fields"]["data.fps"] == 25.0
    assert plan["fields"]["description"] == "Valid update"


def test_invalid_frame_range_ignored_when_frame_unchanged():
    """Requirement 8.3: invalid range not reported when only fps changes."""
    changed = {"fps": 24.0}
    effective = {
        "frameStart": 1050,
        "frameEnd": 1000,
        "fps": 24.0,
    }
    own = ["frameStart", "frameEnd", "fps"]

    plan = plan_attribute_write(changed, effective, own)

    assert plan["fields"] == {"data.fps": 24.0}
    assert plan["errors"] == []
    assert "data.frame_in" not in plan["fields"]
    assert "data.frame_out" not in plan["fields"]
    assert "nb_frames" not in plan["fields"]

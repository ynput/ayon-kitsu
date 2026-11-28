"""Unit tests for Slice 2 attribute and assignee edge cases (Task 18.6).

Validates: Requirements 7.3, 8.2, 8.3, 8.5, 8.6, 8.8, 8.9, 8.10, 14.2
"""

import pytest

from attrib_parsing import parse_attrib
from processor.outbound.mapping import (
    UNRESOLVED_EMAIL_SEVERAL,
    UNRESOLVED_EMAIL_ZERO,
    UNRESOLVED_KITSU_ID_NOT_FOUND,
    UNRESOLVED_NO_KITSU_ID_NO_EMAIL,
    kitsu_attrib_view,
    resolve_assignees,
)
from processor.outbound.planning import plan_attribute_write

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def test_unresolved_assignee_edge_cases():
    """Requirement 7.3, 14.2: unresolved assignees categorized by reason."""
    ayon_users = [
        {
            "name": "u_stale",
            "kitsu_id": "k-stale",
            "email": "stale@studio.com",
        },
        {"name": "u_no_id_no_email", "kitsu_id": None, "email": None},
        {"name": "u_zero", "kitsu_id": None, "email": "zero@studio.com"},
        {"name": "u_dup", "kitsu_id": None, "email": "dup@studio.com"},
        {
            "name": "u_valid",
            "kitsu_id": "k-valid",
            "email": "valid@studio.com",
        },
    ]
    kitsu_persons = [
        {"id": "k-valid", "email": "valid@studio.com"},
        {"id": "k-dup1", "email": "dup@studio.com"},
        {"id": "k-dup2", "email": "dup@studio.com"},
    ]

    requested = [
        "u_stale",
        "u_no_id_no_email",
        "u_zero",
        "u_dup",
        "u_valid",
        "unknown_user",
    ]

    res = resolve_assignees(requested, ayon_users, kitsu_persons)

    assert res["resolved"] == {"u_valid": "k-valid"}
    assert res["unresolved"] == {
        "u_stale": UNRESOLVED_KITSU_ID_NOT_FOUND,
        "u_no_id_no_email": UNRESOLVED_NO_KITSU_ID_NO_EMAIL,
        "u_zero": UNRESOLVED_EMAIL_ZERO,
        "u_dup": UNRESOLVED_EMAIL_SEVERAL,
        "unknown_user": UNRESOLVED_NO_KITSU_ID_NO_EMAIL,
    }


def test_frame_end_below_frame_start_error():
    """Requirement 8.3, 14.2: end < start omits frames and errors."""
    changed = {
        "frameStart": 1050,
        "frameEnd": 1000,
        "fps": 24.0,
        "description": "Invalid frame range shot",
    }
    effective = {
        "frameStart": 1050,
        "frameEnd": 1000,
        "fps": 24.0,
        "description": "Invalid frame range shot",
    }
    own = ["frameStart", "frameEnd", "fps", "description"]

    plan = plan_attribute_write(changed, effective, own)

    assert "data.frame_in" not in plan["fields"]
    assert "data.frame_out" not in plan["fields"]
    assert "nb_frames" not in plan["fields"]
    assert len(plan["errors"]) == 1
    expected_msg = (
        "invalid frame range: frameEnd (1000) < frameStart (1050)"
    )
    assert expected_msg in plan["errors"][0]

    # Other planned fields must be strictly preserved
    assert plan["fields"]["data.fps"] == 24.0
    assert plan["fields"]["description"] == "Invalid frame range shot"


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


def test_inherited_counterpart_used_for_frame_and_resolution():
    """Requirement 8.2, 8.8: unchanged counterpart uses inherited value."""
    # frameStart changed (own), frameEnd unchanged (inherited from parent)
    changed = {"frameStart": 1001, "resolutionWidth": 1920}
    effective = {
        "frameStart": 1001,
        "frameEnd": 1050,  # inherited
        "resolutionWidth": 1920,
        "resolutionHeight": 1080,  # inherited
    }
    own = ["frameStart", "resolutionWidth"]

    plan = plan_attribute_write(changed, effective, own)

    assert plan["fields"]["data.frame_in"] == 1001
    assert plan["fields"]["data.frame_out"] == 1050
    assert plan["fields"]["nb_frames"] == 50
    assert plan["fields"]["data.resolution"] == "1920x1080"
    assert plan["errors"] == []
    assert plan["skipped"] == {}


def test_reverse_counterpart_directions():
    """Requirement 8.2, 8.8: reverse directions for frame and resolution."""
    # frameEnd changed (own), frameStart unchanged (inherited)
    # resolutionHeight changed (own), resolutionWidth unchanged (inherited)
    changed = {"frameEnd": 1050, "resolutionHeight": 1080}
    effective = {
        "frameStart": 1001,  # inherited
        "frameEnd": 1050,
        "resolutionWidth": 1920,  # inherited
        "resolutionHeight": 1080,
    }
    own = ["frameEnd", "resolutionHeight"]

    plan = plan_attribute_write(changed, effective, own)

    assert plan["fields"]["data.frame_in"] == 1001
    assert plan["fields"]["data.frame_out"] == 1050
    assert plan["fields"]["nb_frames"] == 50
    assert plan["fields"]["data.resolution"] == "1920x1080"
    assert plan["errors"] == []
    assert plan["skipped"] == {}


def test_counterpart_changed_and_inherited_suppresses_pair():
    """Requirement 8.6: counterpart changed and inherited skips pair."""
    # frameStart own and changed, but frameEnd changed and inherited
    changed = {"frameStart": 1001, "frameEnd": 1050}
    effective = {"frameStart": 1001, "frameEnd": 1050}
    own = ["frameStart"]

    plan = plan_attribute_write(changed, effective, own)

    assert plan["skipped"]["frameStart"] == "counterpart changed and inherited"
    assert plan["skipped"]["frameEnd"] == "inherited"
    assert "data.frame_in" not in plan["fields"]
    assert "data.frame_out" not in plan["fields"]
    assert "nb_frames" not in plan["fields"]

    # Reverse direction for resolution
    changed_res = {"resolutionWidth": 1920, "resolutionHeight": 1080}
    effective_res = {"resolutionWidth": 1920, "resolutionHeight": 1080}
    own_res = ["resolutionHeight"]

    plan_res = plan_attribute_write(changed_res, effective_res, own_res)

    assert (
        plan_res["skipped"]["resolutionHeight"]
        == "counterpart changed and inherited"
    )
    assert plan_res["skipped"]["resolutionWidth"] == "inherited"
    assert "data.resolution" not in plan_res["fields"]


def test_missing_counterpart_skips_pair_all_directions():
    """Requirement 8.9: missing counterpart skips pair in all directions."""
    # frameStart present, frameEnd missing
    plan1 = plan_attribute_write(
        {"frameStart": 1001},
        {"frameStart": 1001},
        ["frameStart"],
    )
    assert plan1["skipped"]["frameStart"] == "missing value"
    assert "data.frame_in" not in plan1["fields"]
    assert "data.frame_out" not in plan1["fields"]
    assert "nb_frames" not in plan1["fields"]

    # frameEnd present, frameStart missing
    plan2 = plan_attribute_write(
        {"frameEnd": 1050},
        {"frameEnd": 1050},
        ["frameEnd"],
    )
    assert plan2["skipped"]["frameEnd"] == "missing value"
    assert "data.frame_in" not in plan2["fields"]

    # resolutionWidth present, resolutionHeight missing
    plan3 = plan_attribute_write(
        {"resolutionWidth": 1920},
        {"resolutionWidth": 1920},
        ["resolutionWidth"],
    )
    assert plan3["skipped"]["resolutionWidth"] == "missing value"
    assert "data.resolution" not in plan3["fields"]

    # resolutionHeight present, resolutionWidth missing
    plan4 = plan_attribute_write(
        {"resolutionHeight": 1080},
        {"resolutionHeight": 1080},
        ["resolutionHeight"],
    )
    assert plan4["skipped"]["resolutionHeight"] == "missing value"
    assert "data.resolution" not in plan4["fields"]


def test_empty_and_wholly_inherited_or_unmapped_changes():
    """Requirement 8.5, 8.6: empty, wholly inherited, wholly unmapped sets."""
    # Empty changed
    plan_empty = plan_attribute_write({}, {"fps": 24.0}, ["fps"])
    assert plan_empty["fields"] == {}
    assert plan_empty["skipped"] == {}
    assert plan_empty["errors"] == []

    # Wholly inherited
    plan_inh = plan_attribute_write(
        {"fps": 24.0, "description": "hi"},
        {"fps": 24.0, "description": "hi"},
        [],
    )
    assert plan_inh["fields"] == {}
    assert plan_inh["skipped"] == {
        "fps": "inherited",
        "description": "inherited",
    }

    # Wholly unmapped
    plan_unmap = plan_attribute_write(
        {"foo": 1, "bar": 2},
        {"foo": 1, "bar": 2},
        ["foo", "bar"],
    )
    assert plan_unmap["fields"] == {}
    assert plan_unmap["skipped"] == {"foo": "unmapped", "bar": "unmapped"}


def test_inherited_changed_attribute_skipped():
    """Requirement 8.6: changed attribute that is inherited is skipped."""
    changed = {"fps": 30.0, "description": "New description"}
    effective = {"fps": 30.0, "description": "New description"}
    own = ["description"]  # fps is inherited

    plan = plan_attribute_write(changed, effective, own)

    assert plan["skipped"]["fps"] == "inherited"
    assert "data.fps" not in plan["fields"]
    assert plan["fields"]["description"] == "New description"


def test_unmapped_attribute_skipped():
    """Requirement 8.5: unmapped attributes are listed as skipped."""
    changed = {
        "unmappedCustomField": "custom_val",
        "fps": 24.0,
    }
    effective = {
        "unmappedCustomField": "custom_val",
        "fps": 24.0,
    }
    own = ["unmappedCustomField", "fps"]

    plan = plan_attribute_write(changed, effective, own)

    assert plan["skipped"]["unmappedCustomField"] == "unmapped"
    assert plan["errors"] == []
    assert plan["fields"]["data.fps"] == 24.0


def test_empty_description_asymmetry():
    """Requirement 8.10, F14: empty description write vs inbound omission."""
    changed = {"description": ""}
    effective = {"description": ""}
    own = ["description"]

    # 1. Outbound write plans empty string description
    plan = plan_attribute_write(changed, effective, own)
    assert plan["fields"]["description"] == ""

    # 2. Inbound sync preserves empty description (Requirement 8.10)
    kitsu_entity = {"description": "", "data": {}}
    inbound_view = kitsu_attrib_view(kitsu_entity)
    assert inbound_view["description"] == ""

    # 3. Direct parse_attrib from push.py caller boundary preserves empty desc
    push_data = {}
    if "description" in kitsu_entity:
        push_data["description"] = kitsu_entity["description"] or ""
    parsed = parse_attrib(push_data)
    assert parsed["description"] == ""


def test_kitsu_attrib_view_malformed_parity():
    """Property 8: malformed Kitsu entity data parity with inbound parser."""
    with pytest.raises(TypeError):
        kitsu_attrib_view({"data": {"fps": []}})

    with pytest.raises(AttributeError):
        kitsu_attrib_view({"data": {"resolution": 1920}})

    with pytest.raises(TypeError):
        kitsu_attrib_view({"data": {"start_date": 123}})

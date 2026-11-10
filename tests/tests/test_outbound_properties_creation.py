"""Property test for creation plan (Property 22).

Validates: Requirements 11.1, 11.2, 11.5, 11.7, 11.9
"""

# Feature: kitsu-two-way-sync, Property 22: Creation plan (Slice 3)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    CREATION_FOLDER_TYPES,
    SKIP_ALREADY_PAIRED,
    STRUCTURAL_KITSU_IDS,
)
from processor.outbound.planning import plan_creation

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

FOLDER_TYPES = sorted(CREATION_FOLDER_TYPES)
OTHER_FOLDER_TYPES = ["Folder", "ShotGroup", "SequenceGroup", "Custom"]
ALL_FOLDER_TYPES = FOLDER_TYPES + OTHER_FOLDER_TYPES


@settings(max_examples=150, deadline=None)
@given(
    name=st.text(min_size=1, max_size=20),
    folder_type=st.sampled_from(ALL_FOLDER_TYPES),
    kitsu_id=st.one_of(st.none(), st.text(min_size=1, max_size=15)),
    parent_type=st.one_of(st.none(), st.sampled_from(ALL_FOLDER_TYPES)),
    parent_kitsu_id=st.one_of(
        st.none(),
        st.just("sequence"),
        st.just("asset"),
        st.text(min_size=1, max_size=15),
    ),
    has_duplicate=st.booleans(),
    dup_kitsu_id=st.text(min_size=1, max_size=15),
)
def test_creation_plan_folder_property(
    name,
    folder_type,
    kitsu_id,
    parent_type,
    parent_kitsu_id,
    has_duplicate,
    dup_kitsu_id,
):
    """Property 22: folder creation succeeds only when all rules hold."""
    clean_kitsu_id = kitsu_id.strip() if kitsu_id else None
    clean_parent_kitsu_id = (
        parent_kitsu_id.strip() if parent_kitsu_id else None
    )
    clean_dup_id = dup_kitsu_id.strip() or "kitsu-dup-123"

    parent = {
        "folder_type": parent_type,
        "kitsu_id": clean_parent_kitsu_id,
    }
    siblings = []
    if has_duplicate:
        siblings.append({
            "id": clean_dup_id,
            "name": name,
            "type": folder_type,
        })

    plan = plan_creation(
        name=name,
        folder_type=folder_type,
        kitsu_id=clean_kitsu_id,
        parent=parent,
        siblings=siblings,
    )

    # 1. Already paired check
    if clean_kitsu_id:
        assert plan["action"] == "skip"
        assert SKIP_ALREADY_PAIRED in plan["reason"]
        return

    # 2. Folder type check
    if folder_type not in CREATION_FOLDER_TYPES:
        assert plan["action"] == "skip"
        assert "not supported" in plan["reason"]
        return

    # 3. Parent rule check
    parent_rule_ok = False
    if folder_type == "Episode":
        parent_rule_ok = True
    elif folder_type == "Sequence":
        if parent_type == "Episode" and clean_parent_kitsu_id:
            parent_rule_ok = True
        elif clean_parent_kitsu_id == "sequence":
            parent_rule_ok = True
    elif folder_type == "Shot":
        if parent_type == "Sequence" and clean_parent_kitsu_id:
            parent_rule_ok = True
    elif folder_type == "Asset":
        if (
            clean_parent_kitsu_id
            and clean_parent_kitsu_id not in STRUCTURAL_KITSU_IDS
        ):
            parent_rule_ok = True

    if not parent_rule_ok:
        assert plan["action"] == "skip"
        return

    # 4. Duplicate sibling check
    if has_duplicate:
        assert plan["action"] == "skip"
        assert clean_dup_id in plan["reason"]
        assert plan.get("existing_kitsu_id") == clean_dup_id
        return

    # 5. Success
    assert plan["action"] == "create"
    assert plan["entity_type"] == folder_type
    assert plan["name"] == name


@settings(max_examples=150, deadline=None)
@given(
    name=st.text(min_size=1, max_size=20),
    task_type=st.text(min_size=1, max_size=20),
    kitsu_id=st.one_of(st.none(), st.text(min_size=1, max_size=15)),
    parent_type=st.one_of(st.none(), st.sampled_from(ALL_FOLDER_TYPES)),
    parent_kitsu_id=st.one_of(st.none(), st.text(min_size=1, max_size=15)),
    kitsu_task_type_match_count=st.integers(min_value=0, max_value=2),
    has_duplicate=st.booleans(),
    dup_kitsu_id=st.text(min_size=1, max_size=15),
)
def test_creation_plan_task_property(
    name,
    task_type,
    kitsu_id,
    parent_type,
    parent_kitsu_id,
    kitsu_task_type_match_count,
    has_duplicate,
    dup_kitsu_id,
):
    """Property 22: task creation succeeds only when all rules hold."""
    clean_kitsu_id = kitsu_id.strip() if kitsu_id else None
    clean_parent_kitsu_id = (
        parent_kitsu_id.strip() if parent_kitsu_id else None
    )
    clean_dup_id = dup_kitsu_id.strip() or "kitsu-dup-456"

    parent = {
        "folder_type": parent_type,
        "kitsu_id": clean_parent_kitsu_id,
    }

    # Generate Kitsu task types according to match count
    kitsu_task_types = []
    matched_id = "tt-matched-1"
    if kitsu_task_type_match_count == 1:
        kitsu_task_types.append({"id": matched_id, "name": task_type})
    elif kitsu_task_type_match_count == 2:
        kitsu_task_types.append({"id": "tt-1", "name": task_type})
        kitsu_task_types.append({"id": "tt-2", "name": task_type})

    siblings = []
    if has_duplicate:
        siblings.append({
            "id": clean_dup_id,
            "name": task_type,
            "task_type_id": matched_id,
        })

    plan = plan_creation(
        name=name,
        task_type=task_type,
        kitsu_id=clean_kitsu_id,
        parent=parent,
        siblings=siblings,
        kitsu_task_types=kitsu_task_types,
    )

    # 1. Already paired check
    if clean_kitsu_id:
        assert plan["action"] == "skip"
        assert SKIP_ALREADY_PAIRED in plan["reason"]
        return

    # 2. Parent Kitsu ID check
    if not clean_parent_kitsu_id:
        assert plan["action"] == "skip"
        assert "parent folder has no Kitsu id" in plan["reason"]
        return

    # 3. Parent folder type check
    if parent_type not in CREATION_FOLDER_TYPES:
        assert plan["action"] == "skip"
        assert "not a supported paired entity folder" in plan["reason"]
        return

    # 4. Kitsu task type match check
    if kitsu_task_type_match_count != 1:
        assert plan["action"] == "skip"
        return

    # 5. Duplicate task check
    if has_duplicate:
        assert plan["action"] == "skip"
        assert clean_dup_id in plan["reason"]
        assert plan.get("existing_kitsu_id") == clean_dup_id
        return

    # 6. Success
    assert plan["action"] == "create"
    assert plan["entity_type"] == "task"
    assert plan["task_type"] == task_type
    assert plan["task_type_id"] == matched_id
    assert plan["parent_id"] == clean_parent_kitsu_id


def test_creation_plan_unit_examples():
    """Unit tests for creation planning edge cases."""
    # Episode creation at project level
    ep_plan = plan_creation(name="ep01", folder_type="Episode")
    assert ep_plan["action"] == "create"
    assert ep_plan["parent_id"] is None

    # Sequence under Episode
    seq_plan = plan_creation(
        name="sq01",
        folder_type="Sequence",
        parent={"folder_type": "Episode", "kitsu_id": "ep-kitsu-id"},
    )
    assert seq_plan["action"] == "create"
    assert seq_plan["parent_id"] == "ep-kitsu-id"

    # Sequence under sequences root
    seq_root_plan = plan_creation(
        name="sq01",
        folder_type="Sequence",
        parent={"folder_type": "Folder", "kitsu_id": "sequence"},
    )
    assert seq_root_plan["action"] == "create"
    assert seq_root_plan["parent_id"] is None

    # Shot under Sequence
    shot_plan = plan_creation(
        name="sh010",
        folder_type="Shot",
        parent={"folder_type": "Sequence", "kitsu_id": "sq-kitsu-id"},
    )
    assert shot_plan["action"] == "create"
    assert shot_plan["parent_id"] == "sq-kitsu-id"

    # Shot under non-sequence parent fails parent rule
    shot_bad_parent = plan_creation(
        name="sh010",
        folder_type="Shot",
        parent={"folder_type": "Episode", "kitsu_id": "ep-kitsu-id"},
    )
    assert shot_bad_parent["action"] == "skip"
    assert "Shot" in shot_bad_parent["reason"]

    # Asset under asset type folder
    asset_plan = plan_creation(
        name="Hero",
        folder_type="Asset",
        parent={"folder_type": "Folder", "kitsu_id": "asset-type-uuid"},
    )
    assert asset_plan["action"] == "create"
    assert asset_plan["parent_id"] == "asset-type-uuid"

    # Asset directly under structural 'asset' root fails
    asset_bad_root = plan_creation(
        name="Hero",
        folder_type="Asset",
        parent={"folder_type": "Folder", "kitsu_id": "asset"},
    )
    assert asset_bad_root["action"] == "skip"

    # Case-sensitive task type match
    task_plan = plan_creation(
        name="Modeling",
        task_type="Modeling",
        parent={"folder_type": "Asset", "kitsu_id": "asset-uuid"},
        kitsu_task_types=[{"id": "tt-1", "name": "modeling"}],
    )
    # Case mismatch: 'Modeling' != 'modeling'
    assert task_plan["action"] == "skip"
    assert "no Kitsu task type matches" in task_plan["reason"]

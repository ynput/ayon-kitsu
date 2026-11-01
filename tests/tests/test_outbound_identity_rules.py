"""Unit tests for identity rules (Task 6.11).

Validates: Requirements 3.2, 3.5, 3.6, 3.7, 3.8.
"""

import pytest

from processor.outbound.constants import (
    STRUCTURAL_KITSU_IDS,
)
from processor.outbound.identity_rules import (
    AYON_KIND_FOLDER,
    AYON_KIND_TASK,
    AYON_KIND_USER,
    KITSU_ID_MISSING,
    KITSU_ID_OK,
    KITSU_ID_STRUCTURAL,
    TARGET_ERROR_KIND,
    TARGET_ERROR_OWNERS,
    TARGET_ERROR_PROJECT,
    validate_kitsu_id,
    validate_kitsu_target,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


# ---------------------------------------------------------------------------
# validate_kitsu_id (Requirements 3.2, 3.6)
# ---------------------------------------------------------------------------


def test_validate_kitsu_id_missing():
    """Missing, empty or non-string kitsuId is classified as missing."""
    for val in (None, "", 123, ["k1"], {"id": "k1"}):
        res = validate_kitsu_id(val, "ent-1")
        assert res["result"] == KITSU_ID_MISSING
        assert "ent-1" in res["reason"]
        assert "has no Kitsu id" in res["reason"]


def test_validate_kitsu_id_structural_builtins():
    """Built-in structural folder names are classified as structural."""
    for structural in STRUCTURAL_KITSU_IDS:
        res = validate_kitsu_id(structural, "folder-99")
        assert res["result"] == KITSU_ID_STRUCTURAL
        assert "folder-99" in res["reason"]
        assert structural in res["reason"]
        assert "structural folder" in res["reason"]


def test_validate_kitsu_id_structural_asset_type_ids():
    """Asset type ids of the paired project are classified as structural."""
    asset_types = {"asset-type-1", "asset-type-2"}
    res = validate_kitsu_id("asset-type-1", "folder-1", asset_types)
    assert res["result"] == KITSU_ID_STRUCTURAL
    assert "folder-1" in res["reason"]
    assert "asset-type-1" in res["reason"]


def test_validate_kitsu_id_ok():
    """Normal string id returns ok status and kitsu_id."""
    res = validate_kitsu_id("normal-kitsu-id-123", "ent-1")
    assert res["result"] == KITSU_ID_OK
    assert res["kitsu_id"] == "normal-kitsu-id-123"


# ---------------------------------------------------------------------------
# validate_kitsu_target (Requirements 3.5, 3.7, 3.8)
# ---------------------------------------------------------------------------


def test_validate_kitsu_target_duplicate_owners():
    """Duplicate owners in AYON fails with owners error and lists ids."""
    owners = {
        "folders": ["folder-1", "folder-2"],
        "tasks": [],
        "users": [],
    }
    kitsu_entity = {"id": "k1", "type": "Asset", "project_id": "proj-1"}
    res = validate_kitsu_target(
        ayon_kind=AYON_KIND_FOLDER,
        entity_id="folder-1",
        kitsu_id="k1",
        kitsu_entity=kitsu_entity,
        kitsu_project_id="proj-1",
        owners=owners,
    )
    assert res["ok"] is False
    assert res["error"] == TARGET_ERROR_OWNERS
    assert "k1" in res["reason"]
    assert "folder-1" in res["reason"]
    assert "folder-2" in res["reason"]


def test_validate_kitsu_target_kind_mismatch():
    """Kind mismatch between AYON and Kitsu fails with kind error."""
    owners = {"folders": ["folder-1"], "tasks": [], "users": []}
    # AYON folder targeting a Kitsu Task
    kitsu_entity = {"id": "k1", "type": "Task", "project_id": "proj-1"}
    res = validate_kitsu_target(
        ayon_kind=AYON_KIND_FOLDER,
        entity_id="folder-1",
        kitsu_id="k1",
        kitsu_entity=kitsu_entity,
        kitsu_project_id="proj-1",
        owners=owners,
    )
    assert res["ok"] is False
    assert res["error"] == TARGET_ERROR_KIND
    assert "k1" in res["reason"]
    assert "folder-1" in res["reason"]
    assert "folder" in res["reason"]
    assert "Task" in res["reason"]

    # AYON task targeting a Kitsu Shot
    kitsu_shot = {"id": "k2", "type": "Shot", "project_id": "proj-1"}
    owners_task = {"folders": [], "tasks": ["task-1"], "users": []}
    res2 = validate_kitsu_target(
        ayon_kind=AYON_KIND_TASK,
        entity_id="task-1",
        kitsu_id="k2",
        kitsu_entity=kitsu_shot,
        kitsu_project_id="proj-1",
        owners=owners_task,
    )
    assert res2["ok"] is False
    assert res2["error"] == TARGET_ERROR_KIND
    assert "task" in res2["reason"]
    assert "Shot" in res2["reason"]


def test_validate_kitsu_target_project_mismatch():
    """Project mismatch between paired project and Kitsu entity fails."""
    owners = {"folders": [], "tasks": ["task-1"], "users": []}
    kitsu_task = {
        "id": "k-task-1",
        "type": "Task",
        "project_id": "other-proj",
    }
    res = validate_kitsu_target(
        ayon_kind=AYON_KIND_TASK,
        entity_id="task-1",
        kitsu_id="k-task-1",
        kitsu_entity=kitsu_task,
        kitsu_project_id="paired-proj",
        owners=owners,
    )
    assert res["ok"] is False
    assert res["error"] == TARGET_ERROR_PROJECT
    assert "k-task-1" in res["reason"]
    assert "paired-proj" in res["reason"]
    assert "other-proj" in res["reason"]


def test_validate_kitsu_target_user_skips_project_check():
    """Kitsu Person target does not enforce project check."""
    owners = {"folders": [], "tasks": [], "users": ["usr-1"]}
    kitsu_person = {"id": "k-person-1", "type": "Person"}
    res = validate_kitsu_target(
        ayon_kind=AYON_KIND_USER,
        entity_id="usr-1",
        kitsu_id="k-person-1",
        kitsu_entity=kitsu_person,
        kitsu_project_id="any-proj",
        owners=owners,
    )
    assert res["ok"] is True


def test_validate_kitsu_target_success():
    """Matching kind, project, and single owner succeeds."""
    owners = {"folders": [], "tasks": ["task-1"], "users": []}
    kitsu_task = {
        "id": "k-task-1",
        "type": "Task",
        "project_id": "paired-proj",
    }
    res = validate_kitsu_target(
        ayon_kind=AYON_KIND_TASK,
        entity_id="task-1",
        kitsu_id="k-task-1",
        kitsu_entity=kitsu_task,
        kitsu_project_id="paired-proj",
        owners=owners,
    )
    assert res["ok"] is True

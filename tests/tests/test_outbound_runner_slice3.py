"""Unit tests for OutboundJobRunner Slice 3 dispatch (Task 25.7).

Validates: Requirements 5.13, 11.1, 11.2, 11.6, 11.7, 11.9, 12.1, 12.2,
12.3, 12.4, 12.6, 12.7, 12.8.
"""

from unittest.mock import MagicMock

import pytest

from processor.outbound.constants import (
    ENROLLED_TOPICS,
    SLICE_3_TOPICS,
    TOPIC_FOLDER_CREATED,
    TOPIC_FOLDER_DELETED,
    TOPIC_FOLDER_LABEL_CHANGED,
    TOPIC_PROJECT_DELETED,
    TOPIC_TASK_CREATED,
    TOPIC_TASK_DELETED,
    TOPIC_USER_DELETED,
)
from processor.outbound.kitsu_writer import KitsuWriterError

from .offline import block_network  # noqa: F401
from .outbound_harness import (
    KITSU_PROJECT,
    SLICE3_CATEGORIES,
    add_event as _add_event,
    build_runner,
)
from .outbound_fakes import FakeKitsuWriter
from .outbound_harness import PROJECT, add_event, setup_runner
from processor.outbound.constants import (
    DECISION_APPLIED,
    DECISION_FAILED,
    ERROR_UNREACHABLE,
)
from processor.outbound.handlers.deletion import handle_deletion

pytestmark = pytest.mark.usefixtures("block_network")


def _setup(enabled=True):
    """Build a runner with every Slice 3 toggle set to ``enabled``."""
    h = build_runner(SLICE3_CATEGORIES if enabled else ())
    h.writer.tasks["kt-seq-1"] = {
        "id": "kt-seq-1",
        "type": "Sequence",
        "name": "sq010",
        "project_id": KITSU_PROJECT,
    }
    return h.clock, h.store, h.writer, h.runner


def _only_job(store):
    assert len(store.jobs) == 1
    return next(iter(store.jobs.values()))


def _seq_parent(store, kitsu_id="kt-seq-1"):
    data = {"kitsuId": kitsu_id} if kitsu_id else {}
    store.entities[("folder", "fold-seq")] = {
        "id": "fold-seq",
        "name": "sq010",
        "folderType": "Sequence",
        "data": data,
    }


def _shot(store, data=None):
    store.entities[("folder", "fold-shot")] = {
        "id": "fold-shot",
        "name": "sh010",
        "folderType": "Shot",
        "parentId": "fold-seq",
        "data": dict(data or {}),
    }


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


def test_enrolled_topics_include_slice3():
    """Requirement 4.14: ENROLLED_TOPICS holds every Slice 3 topic."""
    for topic in SLICE_3_TOPICS:
        assert topic in ENROLLED_TOPICS


def test_excluded_events_never_enrolled():
    """Requirement 5.13: sync-originated creation is never enrolled."""
    _, store, writer, runner = _setup()
    _seq_parent(store)
    _shot(store)
    _add_event(
        store,
        "evt-c",
        TOPIC_FOLDER_CREATED,
        "fold-shot",
        sender_type="kitsu_sync",
    )
    assert runner.poll_once() is False
    assert store.jobs == {}
    assert writer.created == []
    assert store.enroll_calls[-1]["events_filter"] is not None


def test_enroll_falls_back_when_filter_rejected():
    """Q7: rejected filter falls back; runtime origin check still skips."""
    _, store, writer, runner = _setup()
    store.reject_events_filter = True
    _seq_parent(store)
    _shot(store)
    _add_event(
        store,
        "evt-c",
        TOPIC_FOLDER_CREATED,
        "fold-shot",
        sender_type="kitsu_sync",
    )
    assert runner.poll_once() is True
    job = _only_job(store)
    assert job["status"] == "finished"
    assert "sync originated" in job["description"]
    assert writer.created == []
    assert runner.enroll_filter_supported is False


# ---------------------------------------------------------------------------
# Creation (Requirement 11)
# ---------------------------------------------------------------------------


def test_create_shot_stores_kitsu_id():
    """Requirements 11.1: Shot created under paired Sequence, id stored."""
    _, store, writer, runner = _setup()
    _seq_parent(store)
    _shot(store)
    _add_event(store, "evt-c", TOPIC_FOLDER_CREATED, "fold-shot")

    assert runner.poll_once() is True
    job = _only_job(store)
    assert job["status"] == "finished"
    assert job["description"].startswith("Applied:")
    assert len(writer.created) == 1
    created = writer.created[0]
    assert created["type"] == "Shot"
    assert created["parent_id"] == "kt-seq-1"
    assert created["project_id"] == KITSU_PROJECT
    shot = store.entities[("folder", "fold-shot")]
    assert shot["data"]["kitsuId"] == created["id"]


def test_create_already_paired_skips():
    """Requirement 11.7: entity with kitsuId is not created again."""
    _, store, writer, runner = _setup()
    _seq_parent(store)
    _shot(store, data={"kitsuId": "kt-shot-existing"})
    _add_event(store, "evt-c", TOPIC_FOLDER_CREATED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Skipped:")
    assert "already paired" in job["description"]
    assert writer.created == []


def test_create_parent_without_kitsu_id_skips():
    """Requirement 11.5: parent without kitsuId blocks creation."""
    _, store, writer, runner = _setup()
    _seq_parent(store, kitsu_id=None)
    _shot(store)
    _add_event(store, "evt-c", TOPIC_FOLDER_CREATED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Skipped:")
    assert "no Kitsu id" in job["description"]
    assert writer.created == []


def test_create_duplicate_sibling_skips():
    """Requirement 11.9: same-name sibling in Kitsu blocks creation."""
    _, store, writer, runner = _setup()
    _seq_parent(store)
    _shot(store)
    writer.siblings[("Shot", "kt-seq-1")] = [
        {"id": "kt-dup", "name": "sh010", "type": "Shot"}
    ]
    _add_event(store, "evt-c", TOPIC_FOLDER_CREATED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Skipped:")
    assert "kt-dup" in job["description"]
    assert writer.created == []


def test_create_store_failure_keeps_kitsu_entity():
    """Requirement 11.6: kitsuId store failure fails with both ids."""
    _, store, writer, runner = _setup()
    _seq_parent(store)
    _shot(store)
    store.fail_update_entity = True
    _add_event(store, "evt-c", TOPIC_FOLDER_CREATED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    new_id = writer.created[0]["id"]
    assert new_id in job["description"]
    assert "fold-shot" in job["description"]
    assert writer.removed == []
    assert new_id in writer.tasks


def test_create_kitsu_rejection_leaves_ayon_unpaired():
    """Requirement 11.8: Kitsu rejection fails and stores no kitsuId."""
    _, store, writer, runner = _setup()
    _seq_parent(store)
    _shot(store)
    writer.error_on_create = KitsuWriterError(
        "rejected", "name invalid", http_status=400
    )
    _add_event(store, "evt-c", TOPIC_FOLDER_CREATED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    assert "name invalid" in job["description"]
    assert store.entity_updates == []


def test_create_task_under_paired_shot():
    """Requirement 11.2: task created with the matching Kitsu task type."""
    _, store, writer, runner = _setup()
    store.entities[("folder", "fold-shot")] = {
        "id": "fold-shot",
        "name": "sh010",
        "folderType": "Shot",
        "data": {"kitsuId": "kt-shot-1"},
    }
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
    }
    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "name": "animation",
        "taskType": "Animation",
        "folderId": "fold-shot",
        "data": {},
    }
    _add_event(store, "evt-t", TOPIC_TASK_CREATED, "task-1")

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Applied:")
    created = writer.created[0]
    assert created["task_type_id"] == "tt-anim"
    assert created["entity_id"] == "kt-shot-1"
    task = store.entities[("task", "task-1")]
    assert task["data"]["kitsuId"] == created["id"]


def test_create_task_duplicate_type_skips():
    """Requirement 11.9: task of the same type on the entity blocks."""
    _, store, writer, runner = _setup()
    store.entities[("folder", "fold-shot")] = {
        "id": "fold-shot",
        "name": "sh010",
        "folderType": "Shot",
        "data": {"kitsuId": "kt-shot-1"},
    }
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
    }
    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "name": "animation",
        "taskType": "Animation",
        "folderId": "fold-shot",
        "data": {},
    }
    writer.entity_tasks["kt-shot-1"] = [
        {"id": "kt-task-old", "name": "Animation", "task_type_id": "tt-anim"}
    ]
    _add_event(store, "evt-t", TOPIC_TASK_CREATED, "task-1")

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Skipped:")
    assert "kt-task-old" in job["description"]
    assert writer.created == []


# ---------------------------------------------------------------------------
# Rename (Requirement 12.1, 12.7)
# ---------------------------------------------------------------------------


def _paired_shot(store, writer, label="SH010 final"):
    store.entities[("folder", "fold-shot")] = {
        "id": "fold-shot",
        "name": "sh010",
        "label": label,
        "folderType": "Shot",
        "data": {"kitsuId": "kt-shot-1"},
    }
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
        "description": "keep me",
        "data": {"fps": 24},
    }


def test_rename_writes_only_name():
    """Requirement 12.1: rename writes only the Kitsu name field."""
    _, store, writer, runner = _setup()
    _paired_shot(store, writer)
    _add_event(store, "evt-r", TOPIC_FOLDER_LABEL_CHANGED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Applied:")
    assert "name changed from 'SH010' to 'SH010 final'" in (
        job["description"]
    )
    assert writer.renamed == [
        {
            "kitsu_id": "kt-shot-1",
            "payload": {"name": "SH010 final"},
            "is_task": False,
        }
    ]
    assert writer.tasks["kt-shot-1"]["description"] == "keep me"
    assert writer.tasks["kt-shot-1"]["data"] == {"fps": 24}


def test_rename_in_sync_skips():
    """Requirement 5.4: no write when Kitsu already has the name."""
    _, store, writer, runner = _setup()
    _paired_shot(store, writer, label="SH010")
    _add_event(store, "evt-r", TOPIC_FOLDER_LABEL_CHANGED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Skipped:")
    assert writer.renamed == []


def test_rename_rejected_fails_with_ids_and_operation():
    """Requirement 12.7: rejection names kitsu id, entity and op."""
    _, store, writer, runner = _setup()
    _paired_shot(store, writer)
    writer.error_on_rename = KitsuWriterError(
        "rejected", "duplicate name", http_status=400
    )
    _add_event(store, "evt-r", TOPIC_FOLDER_LABEL_CHANGED, "fold-shot")

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    desc = job["description"]
    assert "kt-shot-1" in desc
    assert "fold-shot" in desc
    assert "rename" in desc


# ---------------------------------------------------------------------------
# Deletion (Requirement 12.2, 12.3, 12.4, 12.6, 12.8)
# ---------------------------------------------------------------------------


def _deleted_payload(kitsu_id="kt-shot-1", name="sh010"):
    return {
        "entityData": {
            "id": "fold-shot",
            "name": name,
            "folderType": "Shot",
            "data": {"kitsuId": kitsu_id} if kitsu_id else {},
        }
    }


def test_delete_without_blockers_removes_entity():
    """Requirements 12.2, 12.4: removal recorded with all identifiers."""
    _, store, writer, runner = _setup()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
    }
    _add_event(
        store,
        "evt-d",
        TOPIC_FOLDER_DELETED,
        "fold-shot",
        payload=_deleted_payload(),
    )

    runner.poll_once()
    job = _only_job(store)
    desc = job["description"]
    assert desc.startswith("Applied:")
    assert "kitsu_id=kt-shot-1" in desc
    assert "name='SH010'" in desc
    assert "type=Shot" in desc
    assert "ayon_id=fold-shot" in desc
    assert writer.removed == [
        {"kitsu_id": "kt-shot-1", "type": "Shot", "force": False}
    ]


def test_delete_blocked_by_counts():
    """Requirement 12.3: comments, previews or children block deletion."""
    _, store, writer, runner = _setup()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
    }
    writer.deletion_counts["kt-shot-1"] = {
        "comments": 2,
        "previews": 1,
        "children": 0,
    }
    _add_event(
        store,
        "evt-d",
        TOPIC_FOLDER_DELETED,
        "fold-shot",
        payload=_deleted_payload(),
    )

    runner.poll_once()
    job = _only_job(store)
    desc = job["description"]
    assert desc.startswith("Skipped:")
    assert "2" in desc and "comments" in desc
    assert "1" in desc and "previews" in desc
    assert writer.removed == []


def test_delete_task_uses_task_lookup():
    """Requirement 12.2: deleted task removes the paired Kitsu task."""
    _, store, writer, runner = _setup()
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "type": "Task",
        "name": "Animation",
        "project_id": KITSU_PROJECT,
    }
    _add_event(
        store,
        "evt-d",
        TOPIC_TASK_DELETED,
        "task-1",
        payload={"entityData": {"data": {"kitsuId": "kt-task-1"}}},
    )

    runner.poll_once()
    job = _only_job(store)
    assert job["description"].startswith("Applied:")
    assert writer.removed[0]["type"] == "Task"


def test_delete_missing_kitsu_id_fails():
    """Requirement 12.8: undeterminable kitsuId fails with entity id."""
    _, store, writer, runner = _setup()
    _add_event(
        store,
        "evt-d",
        TOPIC_FOLDER_DELETED,
        "fold-shot",
        payload=_deleted_payload(kitsu_id=None),
    )

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    assert "fold-shot" in job["description"]
    assert writer.removed == []


def test_delete_rejected_fails_with_ids_and_operation():
    """Requirement 12.7: Kitsu rejection on removal names the operation."""
    _, store, writer, runner = _setup()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
    }
    writer.error_on_remove = KitsuWriterError(
        "rejected", "has dependencies", http_status=400
    )
    _add_event(
        store,
        "evt-d",
        TOPIC_FOLDER_DELETED,
        "fold-shot",
        payload=_deleted_payload(),
    )

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    desc = job["description"]
    assert "kt-shot-1" in desc
    assert "fold-shot" in desc
    assert "delete" in desc


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("topic", [TOPIC_PROJECT_DELETED, TOPIC_USER_DELETED])
def test_project_and_user_deletion_out_of_scope(topic, enabled):
    """Requirement 12.6: out of scope regardless of toggles."""
    _, store, writer, runner = _setup(enabled=enabled)
    _add_event(store, "evt-x", topic, "ent-1")

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "finished"
    assert "project and person deletion is out of scope" in (
        job["description"]
    )
    assert writer.removed == []
    assert writer.renamed == []
    assert writer.created == []


def test_delete_cross_project_rejected():
    """Finding 1 [P1]: cross-project deletion target is rejected safely."""
    _, store, writer, runner = _setup()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": "other-kitsu-project",
    }
    _add_event(
        store,
        "evt-d",
        TOPIC_FOLDER_DELETED,
        "fold-shot",
        payload=_deleted_payload(),
    )

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    desc = job["description"]
    assert "kt-shot-1" in desc
    assert "other-kitsu-project" in desc
    assert "No Kitsu field was written" in desc
    assert writer.removed == []


def test_delete_task_kind_mismatch_rejected():
    """Finding 1 [P1]: deletion of task with non-task Kitsu entity fails."""
    _, store, writer, runner = _setup()
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
    }
    _add_event(
        store,
        "evt-d",
        TOPIC_TASK_DELETED,
        "task-1",
        payload={"entityData": {"data": {"kitsuId": "kt-task-1"}}},
    )

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    desc = job["description"]
    assert "kt-task-1" in desc
    assert "expected a Task" in desc
    assert writer.removed == []


def test_q7_fallback_on_http_422_filter_rejection():
    """Finding 3 [P1]: HTTP 422 filter rejection falls back to unfiltered."""
    _, store, writer, runner = _setup()
    store.fail_filter_enroll = True
    _seq_parent(store)
    _shot(store)
    _add_event(
        store,
        "evt-c",
        TOPIC_FOLDER_CREATED,
        "fold-shot",
    )

    assert runner.enroll_filter_supported is True
    assert runner.poll_once() is True
    assert runner.enroll_filter_supported is False
    job = _only_job(store)
    assert job["status"] == "finished"
    assert len(writer.created) == 1


def test_creation_raw_patch_failure_fails_safely():
    """Finding 9 [P2]: raw PATCH status error fails creation safely."""
    _, store, writer, runner = _setup()
    _seq_parent(store)
    _shot(store)
    _add_event(store, "evt-c", TOPIC_FOLDER_CREATED, "fold-shot")

    store.update_folder = None
    bad_resp = MagicMock()
    bad_resp.status_code = 403
    bad_resp.raise_for_status.side_effect = RuntimeError(
        "HTTP 403 Forbidden"
    )
    store.patch = MagicMock(return_value=bad_resp)

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    desc = job["description"]
    assert "fold-shot" in desc
    assert "kt-new-" in desc
    assert "HTTP 403" in desc
    # Ensure created Kitsu entity is preserved for remediation (11.6)
    assert len(writer.created) == 1
    assert writer.removed == []


def test_deletion_skipped_when_surviving_owner_exists():
    """Deletion must be skipped if another AYON entity owns the kitsuId."""
    _, store, writer, runner, _ = setup_runner()

    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
    }
    writer.deletion_counts["kt-shot-1"] = {
        "comments": 0,
        "previews": 0,
        "children": 0,
    }

    # Add a surviving entity in AYON store that shares the same kitsuId
    store.entities[("folder", "fold-surviving")] = {
        "id": "fold-surviving",
        "name": "sh010_alt",
        "folderType": "Shot",
        "data": {"kitsuId": "kt-shot-1"},
    }

    add_event(
        store,
        "evt-del",
        TOPIC_FOLDER_DELETED,
        "fold-deleted",
        payload={
            "entityData": {
                "id": "fold-deleted",
                "name": "sh010",
                "folderType": "Shot",
                "data": {"kitsuId": "kt-shot-1"},
            }
        },
    )

    runner.poll_once()
    assert len(store.jobs) == 1
    job = next(iter(store.jobs.values()))
    desc = job["description"]
    assert desc.startswith("Skipped:")
    assert "still owned by surviving AYON entity(ies)" in desc
    assert "fold-surviving" in desc
    # Writer delete must NOT have been called
    assert writer.removed == []


def test_deletion_proceeds_when_only_deleted_entity_owned_kitsu_id():
    """Deletion proceeds normally if no other surviving entities exist."""
    _, store, writer, runner, _ = setup_runner()

    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
    }
    writer.deletion_counts["kt-shot-1"] = {
        "comments": 0,
        "previews": 0,
        "children": 0,
    }

    # store.entities does not have any other owner
    add_event(
        store,
        "evt-del-ok",
        TOPIC_FOLDER_DELETED,
        "fold-deleted",
        payload={
            "entityData": {
                "id": "fold-deleted",
                "name": "sh010",
                "folderType": "Shot",
                "data": {"kitsuId": "kt-shot-1"},
            }
        },
    )

    runner.poll_once()
    assert len(store.jobs) == 1
    job = next(iter(store.jobs.values()))
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]
    assert writer.removed == [
        {"kitsu_id": "kt-shot-1", "type": "Shot", "force": False}
    ]


def test_deletion_handler_retries_on_kitsu_owners_failure():
    """Failure querying kitsu-owners in deletion handler must be retryable."""
    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "SH010",
        "project_id": KITSU_PROJECT,
    }

    resolver = MagicMock()
    resolver.get_kitsu_owners.side_effect = RuntimeError("503 Server Error")

    ctx = MagicMock()
    ctx.category = "entity_deletion"
    ctx.event = {
        "topic": TOPIC_FOLDER_DELETED,
        "payload": {
            "entityData": {
                "id": "fold-1",
                "name": "sh010",
                "folderType": "Shot",
                "data": {"kitsuId": "kt-shot-1"},
            }
        },
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.attempt = 1

    res = handle_deletion(ctx)
    assert res.decision == DECISION_FAILED
    assert res.retryable is True
    assert res.error_kind == ERROR_UNREACHABLE
    assert "failed to query kitsu-owners" in res.description


def test_rename_preserves_requested_value_across_inbound_echo():
    """Queued label_changed or renamed preserves newValue across echo."""
    from processor.outbound.handlers.rename import handle_rename

    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "Old Name",
        "project_id": KITSU_PROJECT,
    }

    # 1. label_changed event where inbound echo restored label='Old Name'
    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": writer.tasks["kt-shot-1"],
        "ayon": {
            "id": "fold-1",
            "name": "old_name",
            "label": "Old Name",
        },
    }
    ctx = MagicMock()
    ctx.category = "entity_rename"
    ctx.event = {
        "topic": "entity.folder.label_changed",
        "user": "artist",
        "payload": {"oldValue": "Old Name", "newValue": "New Name"},
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.loop_guard_check.return_value = {"allowed": True}
    ctx.attempt = 1

    res = handle_rename(ctx)
    assert res.decision == DECISION_APPLIED
    assert writer.renamed[-1]["payload"]["name"] == "New Name"

    # 2. renamed event where inbound echo restored name='old_name',
    # label=None
    writer.tasks["kt-shot-1"]["name"] = "old_name"
    resolver.resolve.return_value["ayon"] = {
        "id": "fold-1",
        "name": "old_name",
        "label": None,
    }
    ctx.event = {
        "topic": "entity.folder.renamed",
        "user": "artist",
        "payload": {"oldValue": "old_name", "newValue": "new_shot_slug"},
    }
    res2 = handle_rename(ctx)
    assert res2.decision == DECISION_APPLIED
    assert writer.renamed[-1]["payload"]["name"] == "new_shot_slug"


def test_rename_applies_conflict_policy_kitsu_wins_and_ayon_wins():
    """handle_rename enforces kitsu_wins and ayon_wins on concurrent rename."""
    from processor.outbound.constants import DECISION_CONFLICT
    from processor.outbound.handlers.rename import handle_rename

    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "Kitsu Newer Name",
        "project_id": KITSU_PROJECT,
    }

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": writer.tasks["kt-shot-1"],
        "ayon": {
            "id": "fold-1",
            "name": "ayon_new_name",
            "label": "AYON New Name",
            "folderType": "Shot",
        },
    }

    ctx = MagicMock()
    ctx.category = "entity_rename"
    ctx.event = {
        "topic": "entity.folder.label_changed",
        "user": "artist",
        "payload": {
            "oldValue": "Original Name",
            "newValue": "AYON New Name",
        },
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.processor = MagicMock()
    ctx.loop_guard_check.return_value = {"allowed": True}
    ctx.attempt = 1

    # 1. Under kitsu_wins: do NOT overwrite Kitsu; pull Kitsu back into AYON
    ctx.conflict_policy = "kitsu_wins"
    res_kw = handle_rename(ctx)
    assert res_kw.decision == DECISION_CONFLICT
    assert writer.renamed == []
    ctx.processor.pull_kitsu_entity.assert_called_once()

    # 2. Under ayon_wins: overwrite Kitsu with AYON's target name and return
    # DECISION_CONFLICT
    ctx.conflict_policy = "ayon_wins"
    res_aw = handle_rename(ctx)
    assert res_aw.decision == DECISION_CONFLICT
    assert len(writer.renamed) == 1
    assert writer.renamed[0]["payload"]["name"] == "AYON New Name"

def test_create_task_under_parent_with_duplicate_owners_fails():
    """Task creation beneath an ambiguous parent kitsuId fails safely."""
    _, store, writer, runner = _setup()
    store.entities[("folder", "fold-shot-1")] = {
        "id": "fold-shot-1",
        "name": "sh010",
        "folderType": "Shot",
        "data": {"kitsuId": "kt-shot-dup"},
    }
    # Second folder carrying the same kitsuId (duplicate owner)
    store.entities[("folder", "fold-shot-2")] = {
        "id": "fold-shot-2",
        "name": "sh010_copy",
        "folderType": "Shot",
        "data": {"kitsuId": "kt-shot-dup"},
    }
    writer.tasks["kt-shot-dup"] = {
        "id": "kt-shot-dup",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
    }
    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "name": "animation",
        "taskType": "Animation",
        "folderId": "fold-shot-1",
        "data": {},
    }
    _add_event(store, "evt-t", TOPIC_TASK_CREATED, "task-1")

    runner.poll_once()
    job = _only_job(store)
    assert job["status"] == "failed"
    assert "Parent folder identity invalid" in job["description"]
    assert "carried by 2 AYON entities" in job["description"]
    assert writer.created == []


"""Unit tests for OutboundJobRunner Slice 2 dispatch (Task 19.5).

Validates: Requirements 4.1, 4.14, 7.3, 7.6, 8.3, 8.4, 9.2, 13.2.
"""

from unittest.mock import MagicMock, patch
import pytest

from processor.outbound.constants import (
    ENROLLED_TOPICS,
    RETRY_DELAY_S,
    TOPIC_FOLDER_ATTRIB_CHANGED,
    TOPIC_TASK_ASSIGNEES_CHANGED,
    TOPIC_TASK_ATTRIB_CHANGED,
)
from processor.outbound.kitsu_writer import (
    ERROR_SERVER_ERROR,
    KitsuWriterError,
)

from .offline import block_network  # noqa: F401
from .outbound_harness import SLICE2_CATEGORIES, build_runner

pytestmark = pytest.mark.usefixtures("block_network")


def _setup_slice2_runner(clock=None, store=None, writer=None, policy=None):
    h = build_runner(
        SLICE2_CATEGORIES,
        policy=policy or "kitsu_wins",
        clock=clock,
        store=store,
        writer=writer,
    )
    return h.clock, h.store, h.writer, h.runner


def test_enrolled_topics_includes_slice2():
    """Requirement 4.1, 4.14: ENROLLED_TOPICS contains Slice 2 topics."""
    assert TOPIC_TASK_ASSIGNEES_CHANGED in ENROLLED_TOPICS
    assert TOPIC_FOLDER_ATTRIB_CHANGED in ENROLLED_TOPICS
    assert TOPIC_TASK_ATTRIB_CHANGED in ENROLLED_TOPICS


def test_multi_field_attribute_job_with_conflict():
    """Requirement 8.4, 9.2: non-conflicting field written, conflict kept."""
    clock, store, writer, runner = _setup_slice2_runner()

    # Setup folder entity in AYON
    store.entities[("folder", "fold-1")] = {
        "id": "fold-1",
        "name": "shot01",
        "data": {"kitsuId": "kt-fold-1"},
        "attrib": {"fps": 30.0, "description": "Updated desc"},
        "ownAttrib": ["fps", "description"],
    }

    # Setup Kitsu entity: fps matches oldValue (24.0), description changed
    # concurrently in Kitsu to 'Concurrent kitsu edit'
    writer.tasks["kt-fold-1"] = {
        "id": "kt-fold-1",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "description": "Concurrent kitsu edit",
        "data": {"fps": 24.0},
    }

    # Add change event: oldValue carries previous AYON values
    store.add_source_event(
        event_id="evt-attr-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": {"fps": 24.0, "description": "Original desc"},
            "newValue": {"fps": 30.0, "description": "Updated desc"},
        },
        summary={"entityId": "fold-1"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    # Check writer calls: data.fps was written, description was NOT written
    assert len(writer.updated_fields) == 1
    call = writer.updated_fields[0]
    assert call["kitsu_id"] == "kt-fold-1"
    assert call["fields"]["data.fps"] == 30.0
    assert "description" not in call["fields"]

    # In Kitsu, data.fps is updated, concurrent description is preserved
    assert writer.tasks["kt-fold-1"]["data"]["fps"] == 30.0
    assert (
        writer.tasks["kt-fold-1"]["description"] == "Concurrent kitsu edit"
    )

    # Job is finished with conflict decision
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Conflict:" in job["description"]
    assert "description" in job["description"]


def test_invalid_frame_range_writes_other_fields_then_fails():
    """Requirement 8.3: invalid range writes valid fields, then fails."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-2")] = {
        "id": "fold-2",
        "name": "shot02",
        "data": {"kitsuId": "kt-fold-2"},
        "attrib": {
            "frameStart": 1050,
            "frameEnd": 1000,
            "fps": 24.0,
        },
        "ownAttrib": ["frameStart", "frameEnd", "fps"],
    }
    writer.tasks["kt-fold-2"] = {
        "id": "kt-fold-2",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {},
    }

    store.add_source_event(
        event_id="evt-attr-2",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "newValue": {
                "frameStart": 1050,
                "frameEnd": 1000,
                "fps": 24.0,
            }
        },
        summary={"entityId": "fold-2"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    # Valid attribute (fps) was written
    assert len(writer.updated_fields) == 1
    call = writer.updated_fields[0]
    assert call["fields"]["data.fps"] == 24.0
    assert "data.frame_in" not in call["fields"]
    assert "data.frame_out" not in call["fields"]
    assert "nb_frames" not in call["fields"]

    # Job status is failed due to invalid range
    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert "invalid frame range" in job["description"]
    assert "frameEnd (1000) < frameStart (1050)" in job["description"]


def test_unresolved_assignees_finished():
    """Requirement 7.3: resolvable applied, unresolved listed, job finished."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-a")] = {
        "id": "task-a",
        "name": "anim",
        "data": {"kitsuId": "kt-task-a"},
    }
    writer.tasks["kt-task-a"] = {
        "id": "kt-task-a",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    # AYON users
    store.users = [
        {
            "name": "alice",
            "data": {"kitsuId": "p-alice"},
            "attrib": {"email": "alice@studio.com"},
        },
        {"name": "ghost_user", "data": {}, "attrib": {}},
    ]
    # Kitsu persons
    writer.persons = [
        {"id": "p-alice", "name": "Alice Artist", "email": "alice@studio.com"}
    ]

    # Change event: assign alice and ghost_user
    store.add_source_event(
        event_id="evt-assign-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={"newValue": ["alice", "ghost_user"]},
        summary={"entityId": "task-a"},
        user="coordinator",
    )

    ran = runner.poll_once()
    assert ran is True

    # Alice is assigned
    assert len(writer.assigned) == 1
    assert writer.assigned[0]["person_id"] == "p-alice"

    # Job finished with unresolved user in description
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]
    assert "unresolved assignees: ghost_user" in job["description"]
    assert "Alice Artist" in job["description"]


def test_unmanaged_kitsu_assignee_kept_with_empty_ayon_list():
    """Requirement 7.6: unmanaged Kitsu assignee preserved when AYON empty."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-b")] = {
        "id": "task-b",
        "name": "lighting",
        "data": {"kitsuId": "kt-task-b"},
    }

    # Kitsu task has managed bob and unmanaged external artist
    writer.tasks["kt-task-b"] = {
        "id": "kt-task-b",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": ["p-bob", "p-unmanaged"],
    }

    store.users = [
        {
            "name": "bob",
            "data": {"kitsuId": "p-bob"},
            "attrib": {"email": "bob@studio.com"},
        }
    ]
    writer.persons = [
        {"id": "p-bob", "name": "Bob", "email": "bob@studio.com"},
        {
            "id": "p-unmanaged",
            "name": "External",
            "email": "external@vendor.com",
        },
    ]

    # AYON clears all assignees: []
    store.add_source_event(
        event_id="evt-assign-2",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": ["bob"],
            "newValue": [],
        },
        summary={"entityId": "task-b"},
        user="coordinator",
    )

    ran = runner.poll_once()
    assert ran is True

    # Bob was unassigned
    assert len(writer.unassigned) == 1
    assert writer.unassigned[0]["person_id"] == "p-bob"

    # Unmanaged person was strictly kept
    assert "p-unmanaged" in writer.tasks["kt-task-b"]["assignees"]
    assert "p-bob" not in writer.tasks["kt-task-b"]["assignees"]

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]
    assert "removed assignees: [Bob]" in job["description"]


def test_attribute_refresh_failure_propagates_without_stale_put():
    """Finding 1: Failed entity refresh fails job retryably; no PUT."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-1")] = {
        "id": "fold-1",
        "name": "shot01",
        "data": {"kitsuId": "kt-fold-1"},
        "attrib": {"fps": 30.0},
        "ownAttrib": ["fps"],
    }
    writer.tasks["kt-fold-1"] = {
        "id": "kt-fold-1",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"fps": 24.0},
    }
    writer.error_on_get_entity = KitsuWriterError(
        ERROR_SERVER_ERROR, "Kitsu 503", http_status=503, retryable=True
    )

    store.add_source_event(
        event_id="evt-attr-503",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": {"fps": 24.0},
            "newValue": {"fps": 30.0},
        },
        summary={"entityId": "fold-1"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    assert len(writer.updated_fields) == 0
    job = store.jobs["job-1"]
    assert job["status"] == "pending"


def test_assignees_fetch_failure_fails_retryably():
    """Finding 2: Failed AYON users lookup fails job retryably."""
    clock, store, writer, runner = _setup_slice2_runner()
    store.fail_get_users = True

    store.entities[("task", "task-err")] = {
        "id": "task-err",
        "name": "anim",
        "data": {"kitsuId": "kt-task-err"},
    }
    writer.tasks["kt-task-err"] = {
        "id": "kt-task-err",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    store.add_source_event(
        event_id="evt-assign-err",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={"newValue": ["bob"]},
        summary={"entityId": "task-err"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    assert "Failed to fetch AYON users" in job["description"]


def test_multi_field_loop_guard_accumulates_and_suppresses():
    """Finding 3: Multiple fields in one write record all guard keys."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-guard")] = {
        "id": "fold-guard",
        "name": "shot01",
        "data": {"kitsuId": "kt-guard"},
        "attrib": {"fps": 30.0, "description": "New"},
        "ownAttrib": ["fps", "description"],
    }
    writer.tasks["kt-guard"] = {
        "id": "kt-guard",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "description": "Old",
        "data": {"fps": 24.0},
    }

    store.add_source_event(
        event_id="evt-guard-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": {"fps": 24.0, "description": "Old"},
            "newValue": {"fps": 30.0, "description": "New"},
        },
        summary={"entityId": "fold-guard"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    # Both fps and description must exist in runner.loop_guard_state
    fps_key = ("fold-guard", "data.fps")
    desc_key = ("fold-guard", "description")
    assert fps_key in runner.loop_guard_state
    assert desc_key in runner.loop_guard_state


def test_slice2_inbound_refresh_on_conflict():
    """Finding 4: Inbound refresh is requested on kitsu_wins conflict."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.users = [
        {
            "name": "alice",
            "kitsu_id": "p-alice",
            "email": "alice@studio.com",
            "active": True,
        }
    ]
    writer.persons = [
        {"id": "p-alice", "name": "Alice", "email": "alice@studio.com"}
    ]
    store.entities[("task", "task-conf")] = {
        "id": "task-conf",
        "name": "anim",
        "data": {"kitsuId": "kt-task-conf"},
    }
    writer.tasks["kt-task-conf"] = {
        "id": "kt-task-conf",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": ["p-alice"],
    }

    store.add_source_event(
        event_id="evt-assign-conf",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": [],
            "newValue": ["unknown_user"],
        },
        summary={"entityId": "task-conf"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    # Verify processor inbound pull was requested
    assert runner.processor.pull_kitsu_task.called
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Conflict:" in job["description"]


def test_attribute_partial_in_sync_component_not_erased():
    """Finding 5: In-sync frameStart does not erase frameEnd write."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-fr")] = {
        "id": "fold-fr",
        "name": "shot01",
        "data": {"kitsuId": "kt-fr"},
        "attrib": {"frameStart": 1001, "frameEnd": 1030},
        "ownAttrib": ["frameStart", "frameEnd"],
    }
    # Kitsu already has frame_in=1001 (in-sync), but old frame_out=1020
    writer.tasks["kt-fr"] = {
        "id": "kt-fr",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"frame_in": 1001, "frame_out": 1020},
    }

    store.add_source_event(
        event_id="evt-fr-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": {"frameStart": 1001, "frameEnd": 1020},
            "newValue": {"frameStart": 1001, "frameEnd": 1030},
        },
        summary={"entityId": "fold-fr"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    # PUT was issued for data.frame_out and nb_frames (not erased!)
    assert len(writer.updated_fields) == 1
    call = writer.updated_fields[0]
    assert call["fields"]["data.frame_out"] == 1030
    assert call["fields"]["nb_frames"] == 30
    assert "data.frame_in" not in call["fields"]

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]


def test_attribute_empty_own_attrib_treated_as_inherited():
    """Finding 6: ownAttrib=[] marks attrs as inherited, skipping write."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-inh")] = {
        "id": "fold-inh",
        "name": "shot01",
        "data": {"kitsuId": "kt-inh"},
        "attrib": {"fps": 30.0},
        "ownAttrib": [],
    }
    writer.tasks["kt-inh"] = {
        "id": "kt-inh",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"fps": 24.0},
    }

    store.add_source_event(
        event_id="evt-inh-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": {"fps": 24.0},
            "newValue": {"fps": 30.0},
        },
        summary={"entityId": "fold-inh"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    # Zero writes sent
    assert len(writer.updated_fields) == 0
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Skipped:" in job["description"]
    assert "inherited" in job["description"]


def test_assignees_partial_write_retry_succeeds():
    """Finding 7: Partial assignee write retries without false conflict."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.users = [
        {"name": "alice", "kitsu_id": "p-alice", "email": "a@s.com"},
        {"name": "bob", "kitsu_id": "p-bob", "email": "b@s.com"},
    ]
    writer.persons = [
        {"id": "p-alice", "name": "Alice", "email": "a@s.com"},
        {"id": "p-bob", "name": "Bob", "email": "b@s.com"},
    ]

    store.entities[("task", "task-retry")] = {
        "id": "task-retry",
        "name": "anim",
        "data": {"kitsuId": "kt-retry"},
    }
    writer.tasks["kt-retry"] = {
        "id": "kt-retry",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": ["p-bob"],
    }

    # Attempt 1: unassign Bob fails with 503
    writer.error_on_unassign = KitsuWriterError(
        ERROR_SERVER_ERROR, "Kitsu 503", http_status=503, retryable=True
    )

    store.add_source_event(
        event_id="evt-retry-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": ["bob"],
            "newValue": ["alice"],
        },
        summary={"entityId": "task-retry"},
        user="test-user",
    )

    # Attempt 1 runs
    ran = runner.poll_once()
    assert ran is True
    assert len(writer.assigned) == 1
    assert writer.assigned[0]["person_id"] == "p-alice"
    job = store.jobs["job-1"]
    assert job["status"] == "pending"

    # Attempt 2: Kitsu 503 cleared, retry runs
    writer.error_on_unassign = None
    clock.advance(30.0)

    ran2 = runner.poll_once()
    assert ran2 is True
    assert len(writer.unassigned) == 1
    assert writer.unassigned[0]["person_id"] == "p-bob"

    assert writer.tasks["kt-retry"]["assignees"] == ["p-alice"]
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]


def test_assignee_description_zou_person_model_sorted():
    """Findings 8 & 9: Zou person records sorted by full name."""
    clock, store, writer, runner = _setup_slice2_runner()

    # Kitsu persons use first_name and last_name without 'name' key
    writer.persons = [
        {
            "id": "p-z",
            "first_name": "Zach",
            "last_name": "Taylor",
            "email": "z@s.com",
        },
        {
            "id": "p-a",
            "first_name": "Alice",
            "last_name": "Baker",
            "email": "a@s.com",
        },
    ]
    store.users = [
        {"name": "zach", "kitsu_id": "p-z", "email": "z@s.com"},
        {"name": "alice", "kitsu_id": "p-a", "email": "a@s.com"},
    ]

    store.entities[("task", "task-zou")] = {
        "id": "task-zou",
        "name": "anim",
        "data": {"kitsuId": "kt-zou"},
    }
    writer.tasks["kt-zou"] = {
        "id": "kt-zou",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    store.add_source_event(
        event_id="evt-zou-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": [],
            "newValue": ["zach", "alice"],
        },
        summary={"entityId": "task-zou"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]
    # Formatted full names are sorted: Alice Baker before Zach Taylor
    assert (
        "added assignees: [Alice Baker, Zach Taylor]" in job["description"]
    )


def test_composite_resolution_unchanged_counterpart_uses_effective():
    """Requirement 8.2, 8.8: unchanged height uses AYON effective."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-res")] = {
        "id": "fold-res",
        "name": "shot01",
        "attrib": {"resolutionWidth": 1920, "resolutionHeight": 1080},
        "data": {"kitsuId": "kt-fold-res"},
    }
    writer.tasks["kt-fold-res"] = {
        "id": "kt-fold-res",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"resolution": "1280x720"},
    }

    store.add_source_event(
        event_id="evt-res-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1020.0,
        payload={
            "oldValue": {"resolutionWidth": 1280},
            "newValue": {"resolutionWidth": 1920},
        },
        summary={"entityId": "fold-res"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]
    assert len(writer.updated_fields) == 1
    # Must write 1920x1080 (AYON effective height), NOT 1920x720
    assert (
        writer.updated_fields[0]["fields"].get("data.resolution")
        == "1920x1080"
    )


def test_composite_resolution_conflict_kitsu_wins_omits_resolution_write():
    """Requirement 8.2, 9.2: conflict on width writes nothing."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-res-c")] = {
        "id": "fold-res-c",
        "name": "shot01",
        "attrib": {"resolutionWidth": 3840, "resolutionHeight": 2160},
        "data": {"kitsuId": "kt-fold-res-c"},
    }
    writer.tasks["kt-fold-res-c"] = {
        "id": "kt-fold-res-c",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"resolution": "1920x1080"},
    }

    store.add_source_event(
        event_id="evt-res-c-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1030.0,
        payload={
            "oldValue": {"resolutionWidth": 1280},
            "newValue": {"resolutionWidth": 3840},
        },
        summary={"entityId": "fold-res-c"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Conflict:" in job["description"]
    assert len(writer.updated_fields) == 0


def test_composite_frame_range_conflict_kitsu_wins_omits_frame_writes():
    """Requirement 8.2, 9.2: conflict on frameStart writes nothing."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-fr-c")] = {
        "id": "fold-fr-c",
        "name": "shot01",
        "attrib": {"frameStart": 1001, "frameEnd": 1050},
        "data": {"kitsuId": "kt-fold-fr-c"},
    }
    writer.tasks["kt-fold-fr-c"] = {
        "id": "kt-fold-fr-c",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"frame_in": 1, "frame_out": 50},
    }

    store.add_source_event(
        event_id="evt-fr-c-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1040.0,
        payload={
            "oldValue": {"frameStart": 100},
            "newValue": {"frameStart": 1001},
        },
        summary={"entityId": "fold-fr-c"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Conflict:" in job["description"]
    assert len(writer.updated_fields) == 0


def test_intervening_lookup_failure_preserves_prior_writes_across_retries():
    """Requirement 11.2: prior writes preserved on retry failure."""
    clock, store, writer, runner = _setup_slice2_runner()

    writer.persons = [
        {"id": "p-1", "name": "Alice", "email": "alice@s.com"},
        {"id": "p-2", "name": "Bob", "email": "bob@s.com"},
    ]
    store.users = [
        {"name": "alice", "kitsu_id": "p-1", "email": "alice@s.com"},
        {"name": "bob", "kitsu_id": "p-2", "email": "bob@s.com"},
    ]

    store.entities[("task", "task-retry-w")] = {
        "id": "task-retry-w",
        "name": "comp",
        "data": {"kitsuId": "kt-retry-w"},
    }
    writer.tasks["kt-retry-w"] = {
        "id": "kt-retry-w",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    orig_assign = writer.assign

    def flaky_assign(task, person_id):
        if person_id == "p-2":
            raise KitsuWriterError("net_err", "Kitsu timeout", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = flaky_assign

    store.add_source_event(
        event_id="evt-retry-w-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1050.0,
        payload={"oldValue": [], "newValue": ["alice", "bob"]},
        summary={"entityId": "task-retry-w"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    assert len(job["summary"]["writes"]) == 1
    assert job["summary"]["writes"][0]["person_name"] == "Alice"

    # Attempt 2: lookup fails before writer is called
    store.fail_get_users = True
    clock.advance(20.0)  # Pass retry backoff
    ran = runner.poll_once()
    assert ran is True

    # Writes history from attempt 1 must NOT be overwritten with []
    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    assert len(job["summary"]["writes"]) == 1
    assert job["summary"]["writes"][0]["person_name"] == "Alice"


def test_writer_failure_does_not_commit_loop_guard():
    """Requirement 5.9: loop guard state committed ONLY after write."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-guard-fail")] = {
        "id": "fold-guard-fail",
        "name": "shot01",
        "attrib": {"fps": 25.0},
        "data": {"kitsuId": "kt-guard-fail"},
    }
    writer.tasks["kt-guard-fail"] = {
        "id": "kt-guard-fail",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"fps": 24.0},
    }

    writer.error_on_update_fields = KitsuWriterError(
        "net_err", "Connection refused", retryable=True
    )

    store.add_source_event(
        event_id="evt-guard-fail-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1060.0,
        payload={"oldValue": {"fps": 24.0}, "newValue": {"fps": 25.0}},
        summary={"entityId": "fold-guard-fail"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    assert runner.loop_guard_state == {}
    assert getattr(runner, "_pending_guard_state", None) is None


def test_fetch_ayon_users_http_error_fails_retryably_without_finishing():
    """Requirement 7.2: HTTP >= 400 from /users endpoint raises and retries."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-http-err")] = {
        "id": "task-http-err",
        "name": "comp",
        "data": {"kitsuId": "kt-http-err"},
    }
    writer.tasks["kt-http-err"] = {
        "id": "kt-http-err",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    err_resp = MagicMock()
    err_resp.status_code = 503
    err_resp.data = {"detail": "Backend unavailable"}
    orig_get = store.get

    def get_with_users_error(url):
        if "/users" in url or url.endswith("/users"):
            return err_resp
        return orig_get(url)

    store.get = get_with_users_error

    store.add_source_event(
        event_id="evt-http-err-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1070.0,
        payload={"oldValue": [], "newValue": ["alice"]},
        summary={"entityId": "task-http-err"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True
    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    assert job["summary"]["errorKind"] == "server_error"


def test_exhausted_retries_final_failure_includes_partial_writes():
    """Requirement 11.4, 13.3: failed description includes writes."""
    clock, store, writer, runner = _setup_slice2_runner()

    writer.persons = [
        {"id": "p-1", "name": "Alice", "email": "alice@s.com"},
        {"id": "p-2", "name": "Bob", "email": "bob@s.com"},
    ]
    store.users = [
        {"name": "alice", "kitsu_id": "p-1", "email": "alice@s.com"},
        {"name": "bob", "kitsu_id": "p-2", "email": "bob@s.com"},
    ]

    store.entities[("task", "task-exh")] = {
        "id": "task-exh",
        "name": "comp",
        "data": {"kitsuId": "kt-exh"},
    }
    writer.tasks["kt-exh"] = {
        "id": "kt-exh",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    orig_assign = writer.assign

    def flaky_assign(task, person_id):
        if person_id == "p-2":
            raise KitsuWriterError("net_err", "Kitsu timeout", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = flaky_assign

    store.add_source_event(
        event_id="evt-exh-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1080.0,
        payload={"oldValue": [], "newValue": ["alice", "bob"]},
        summary={"entityId": "task-exh"},
        user="test-user",
    )

    # Attempt 1
    runner.poll_once()
    # Attempt 2
    clock.advance(20.0)
    runner.poll_once()
    # Attempt 3
    clock.advance(40.0)
    runner.poll_once()
    # Attempt 4 (final attempt, exhausts MAX_ATTEMPTS)
    clock.advance(80.0)
    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert "Written fields:" in job["description"]
    assert "assigned Alice" in job["description"]
    assert "No Kitsu field was written" not in job["description"]


def test_inbound_pull_on_conflict_supports_edit_and_concept():
    """Requirement 9.4: inbound pull on conflict supports edit and concept."""
    from processor.processor import KitsuProcessor

    proc = MagicMock(spec=KitsuProcessor)
    proc.pull_kitsu_entity = KitsuProcessor.pull_kitsu_entity.__get__(proc)

    with patch(
        "processor.update_from_kitsu.create_or_update_edit"
    ) as mock_edit, patch(
        "processor.update_from_kitsu.create_or_update_concept"
    ) as mock_concept:
        mock_edit.return_value = MagicMock(status_code=200)
        mock_concept.return_value = MagicMock(status_code=200)

        proc.pull_kitsu_entity(
            "kt-edit-1", "edit", {"project_id": "proj-1"}
        )
        mock_edit.assert_called_once_with(
            proc, {"edit_id": "kt-edit-1", "project_id": "proj-1"}
        )

        proc.pull_kitsu_entity(
            "kt-cpt-1", "concept", {"project_id": "proj-1"}
        )
        mock_concept.assert_called_once_with(
            proc, {"concept_id": "kt-cpt-1", "project_id": "proj-1"}
        )

        with pytest.raises(ValueError, match="Unsupported.*entity type"):
            proc.pull_kitsu_entity("kt-bad-1", "unknown_type", {})


def test_frame_range_writes_both_counterparts_when_different():
    """Audit #3 P1: write effective counterpart when differing from kitsu."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-fr")] = {
        "id": "fold-fr",
        "name": "shot02",
        "data": {"kitsuId": "kt-fold-fr"},
        "attrib": {
            "frameStart": 1001,
            "frameEnd": 1050,
            "clipIn": 1001,
            "clipOut": 1050,
        },
        "ownAttrib": ["frameStart", "frameEnd"],
    }
    writer.tasks["kt-fold-fr"] = {
        "id": "kt-fold-fr",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {
            "frame_in": 1,
            "frame_out": 50,
            "nb_frames": 50,
        },
    }

    # Only frameEnd changed in this AYON event
    store.add_source_event(
        event_id="evt-fr-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "oldValue": {"frameEnd": 50},
            "newValue": {"frameEnd": 1050},
        },
        summary={"entityId": "fold-fr"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    # Both frame_in and frame_out should be updated to AYON effective values
    assert len(writer.updated_fields) == 1
    call = writer.updated_fields[0]
    assert call["fields"]["data.frame_in"] == 1001
    assert call["fields"]["data.frame_out"] == 1050


def test_frame_range_changed_endpoint_in_sync_corrects_counterpart():
    """Audit #4 P1: in-sync changed endpoint still corrects counterpart."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-fr2")] = {
        "id": "fold-fr2",
        "name": "shot02b",
        "data": {"kitsuId": "kt-fold-fr2"},
        "attrib": {
            "frameStart": 1001,
            "frameEnd": 1050,
            "clipIn": 1001,
            "clipOut": 1050,
        },
        "ownAttrib": ["frameStart", "frameEnd"],
    }
    # Kitsu already has frame_out=1050, but frame_in=1 and nb_frames=1050
    writer.tasks["kt-fold-fr2"] = {
        "id": "kt-fold-fr2",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "nb_frames": 1050,
        "data": {
            "frame_in": 1,
            "frame_out": 1050,
        },
    }

    # Only frameEnd was changed to 1050
    store.add_source_event(
        event_id="evt-fr2-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={
            "newValue": {"frameEnd": 1050},
        },
        summary={"entityId": "fold-fr2"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    assert len(writer.updated_fields) == 1
    call = writer.updated_fields[0]
    assert call["fields"]["data.frame_in"] == 1001
    assert call["fields"]["nb_frames"] == 50
    assert "data.frame_out" not in call["fields"]


def test_assignee_loop_guard_commits_immediately_per_mutation():
    """Audit #3 P1: loop guard commits after each successful write."""
    clock, store, writer, runner = _setup_slice2_runner()

    writer.persons = [
        {"id": "p-1", "name": "Alice", "email": "alice@s.com"},
        {"id": "p-2", "name": "Bob", "email": "bob@s.com"},
    ]
    store.users = [
        {"name": "alice", "kitsu_id": "p-1", "email": "alice@s.com"},
        {"name": "bob", "kitsu_id": "p-2", "email": "bob@s.com"},
    ]
    store.entities[("task", "task-lg")] = {
        "id": "task-lg",
        "name": "comp",
        "data": {"kitsuId": "kt-lg"},
    }
    writer.tasks["kt-lg"] = {
        "id": "kt-lg",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    orig_assign = writer.assign

    def fail_on_bob(task, person_id):
        if person_id == "p-2":
            raise KitsuWriterError("net_err", "Bob failed", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_on_bob

    store.add_source_event(
        event_id="evt-lg-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1020.0,
        payload={"oldValue": [], "newValue": ["alice", "bob"]},
        summary={"entityId": "task-lg"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    assert runner.loop_guard_state.get(("task-lg", "assignees")) is not None


def test_already_in_sync_preserves_prior_writes_in_description():
    """Audit #3 P2: in-sync exit after partial writes describes writes."""
    clock, store, writer, runner = _setup_slice2_runner()

    writer.persons = [
        {"id": "p-1", "name": "Alice", "email": "alice@s.com"},
        {"id": "p-2", "name": "Bob", "email": "bob@s.com"},
    ]
    store.users = [
        {"name": "alice", "kitsu_id": "p-1", "email": "alice@s.com"},
        {"name": "bob", "kitsu_id": "p-2", "email": "bob@s.com"},
    ]
    store.entities[("task", "task-sync")] = {
        "id": "task-sync",
        "name": "comp",
        "data": {"kitsuId": "kt-sync"},
    }
    writer.tasks["kt-sync"] = {
        "id": "kt-sync",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    orig_assign = writer.assign
    fail_bob = True

    def flake_on_bob(task, person_id):
        if person_id == "p-2" and fail_bob:
            raise KitsuWriterError("net_err", "Bob failed", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = flake_on_bob

    store.add_source_event(
        event_id="evt-sync-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1030.0,
        payload={"oldValue": [], "newValue": ["alice", "bob"]},
        summary={"entityId": "task-sync"},
        user="test-user",
    )

    runner.poll_once()
    writer.tasks["kt-sync"]["assignees"] = ["p-1", "p-2"]
    clock.advance(20.0)
    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Written fields:" in job["description"]
    assert "assigned Alice" in job["description"]
    assert "No Kitsu field was written" not in job["description"]


def test_runner_gated_disabled_category_preserves_prior_writes():
    """Audit #4 P2: runner-level disabled category exit describes writes."""
    clock, store, writer, runner = _setup_slice2_runner()

    writer.persons = [
        {"id": "p-1", "name": "Alice", "email": "alice@s.com"},
        {"id": "p-2", "name": "Bob", "email": "bob@s.com"},
    ]
    store.users = [
        {"name": "alice", "kitsu_id": "p-1", "email": "alice@s.com"},
        {"name": "bob", "kitsu_id": "p-2", "email": "bob@s.com"},
    ]
    store.entities[("task", "task-dis")] = {
        "id": "task-dis",
        "name": "comp",
        "data": {"kitsuId": "kt-dis"},
    }
    writer.tasks["kt-dis"] = {
        "id": "kt-dis",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    orig_assign = writer.assign

    def fail_on_bob(task, person_id):
        if person_id == "p-2":
            raise KitsuWriterError("net_err", "Bob failed", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_on_bob

    store.add_source_event(
        event_id="evt-dis-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1035.0,
        payload={"oldValue": [], "newValue": ["alice", "bob"]},
        summary={"entityId": "task-dis"},
        user="test-user",
    )

    # Attempt 1: Alice assigned, Bob fails
    runner.poll_once()

    # Disable task_assignees before retry
    store.studio_settings["sync_settings"]["two_way_sync"][
        "task_assignees"
    ] = False
    runner.settings_watcher.refresh()

    # Attempt 2: Category disabled, runner skips
    clock.advance(20.0)
    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Written fields:" in job["description"]
    assert "assigned Alice" in job["description"]
    assert "No Kitsu field was written" not in job["description"]


def test_subsequent_lookup_failure_preserves_unwritten_assignees():
    """Audit #4 P2: lookup failure does not erase unwritten assignees."""
    clock, store, writer, runner = _setup_slice2_runner()

    writer.persons = [
        {"id": "p-1", "name": "Alice", "email": "alice@s.com"},
        {"id": "p-2", "name": "Bob", "email": "bob@s.com"},
    ]
    store.users = [
        {"name": "alice", "kitsu_id": "p-1", "email": "alice@s.com"},
        {"name": "bob", "kitsu_id": "p-2", "email": "bob@s.com"},
    ]
    store.entities[("task", "task-lkp")] = {
        "id": "task-lkp",
        "name": "comp",
        "data": {"kitsuId": "kt-lkp"},
    }
    writer.tasks["kt-lkp"] = {
        "id": "kt-lkp",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }

    orig_assign = writer.assign

    def fail_on_bob(task, person_id):
        if person_id == "p-2":
            raise KitsuWriterError("net_err", "Bob failed", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_on_bob

    store.add_source_event(
        event_id="evt-lkp-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1040.0,
        payload={"oldValue": [], "newValue": ["alice", "bob"]},
        summary={"entityId": "task-lkp"},
        user="test-user",
    )

    # Attempt 1: Alice assigned, Bob fails
    runner.poll_once()

    # Now make /users fail on subsequent attempts
    orig_get = store.get
    err_resp = MagicMock()
    err_resp.status_code = 500
    err_resp.text = "Internal Server Error"

    def users_fail(url):
        if "/users" in url or url.endswith("/users"):
            return err_resp
        return orig_get(url)

    store.get = users_fail

    # Attempt 2
    clock.advance(20.0)
    runner.poll_once()
    # Attempt 3
    clock.advance(40.0)
    runner.poll_once()
    # Attempt 4 (final attempt, exhausts retries)
    clock.advance(80.0)
    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert "Written fields:" in job["description"]
    assert "assigned Alice" in job["description"]
    assert "Bob" in job["description"]
    assert "unwritten values:" in job["description"].lower()
    assert job["summary"]["notWritten"] == {"assignees": ["Bob"]}


def test_assignee_writes_use_sorted_person_names_for_before_and_sent():
    """Requirement 13.2: assignee writes use sorted person names."""
    clock, store, writer, runner = _setup_slice2_runner()

    writer.persons = [
        {"id": "p-1", "name": "Alice", "email": "alice@s.com"},
        {
            "id": "p-zou",
            "first_name": "Jean",
            "last_name": "Dupont",
            "email": "jean@s.com",
        },
        {"id": "p-2", "name": "Bob", "email": "bob@s.com"},
    ]
    store.users = [
        {"name": "alice", "kitsu_id": "p-1", "email": "alice@s.com"},
        {"name": "jdupont", "kitsu_id": "p-zou", "email": "jean@s.com"},
        {"name": "bob", "kitsu_id": "p-2", "email": "bob@s.com"},
    ]
    store.entities[("task", "task-names")] = {
        "id": "task-names",
        "name": "comp",
        "data": {"kitsuId": "kt-names"},
    }
    writer.tasks["kt-names"] = {
        "id": "kt-names",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": ["p-1"],
    }

    store.add_source_event(
        event_id="evt-names-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1050.0,
        payload={
            "oldValue": ["alice"],
            "newValue": ["alice", "jdupont", "bob"],
        },
        summary={"entityId": "task-names"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert (
        "wrote assignees (before: [Alice], sent: [Alice, Bob, Jean Dupont])"
        in job["description"]
    )


def test_attribute_write_description_records_actual_before_value():
    """Audit #3 P2: applied attribute write records actual before value."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-bef")] = {
        "id": "fold-bef",
        "name": "shot03",
        "data": {"kitsuId": "kt-fold-bef"},
        "attrib": {"fps": 30.0},
        "ownAttrib": ["fps"],
    }
    writer.tasks["kt-fold-bef"] = {
        "id": "kt-fold-bef",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"fps": 24.0},
    }

    store.add_source_event(
        event_id="evt-bef-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1055.0,
        payload={
            "oldValue": {"fps": 24.0},
            "newValue": {"fps": 30.0},
        },
        summary={"entityId": "fold-bef"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "data.fps (before: 24" in job["description"]
    assert "before: none" not in job["description"]


def test_attribute_write_without_old_value_annotates_no_previous():
    """Requirement 9.6: attribute write without oldValue annotates npv."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-npv")] = {
        "id": "fold-npv",
        "name": "shot05",
        "data": {"kitsuId": "kt-fold-npv"},
        "attrib": {"fps": 25.0},
        "ownAttrib": ["fps"],
    }
    writer.tasks["kt-fold-npv"] = {
        "id": "kt-fold-npv",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "data": {"fps": 24.0},
    }

    store.add_source_event(
        event_id="evt-npv-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1060.0,
        payload={
            "newValue": {"fps": 25.0},
        },
        summary={"entityId": "fold-npv"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "no previous value for fps" in job["description"]


def test_attribute_failure_records_unwritten_attributes():
    """Requirement 10.6, 13.3: failed attribute write records unwritten."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-fail")] = {
        "id": "fold-fail",
        "name": "shot06",
        "data": {"kitsuId": "kt-fold-fail"},
        "attrib": {"fps": 60.0, "description": "New description"},
        "ownAttrib": ["fps", "description"],
    }
    writer.tasks["kt-fold-fail"] = {
        "id": "kt-fold-fail",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "description": "Old description",
        "data": {"fps": 24.0},
    }

    def perm_fail(entity, fields):
        raise KitsuWriterError("perm", "Forbidden", retryable=False)

    writer.update_entity_fields = perm_fail

    store.add_source_event(
        event_id="evt-fail-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1070.0,
        payload={
            "oldValue": {"fps": 24.0, "description": "Old description"},
            "newValue": {"fps": 60.0, "description": "New description"},
        },
        summary={"entityId": "fold-fail"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert "unwritten values:" in job["description"].lower()
    assert "data.fps" in str(job["summary"]["notWritten"])
    assert "description" in str(job["summary"]["notWritten"])


def test_terminal_lookup_failure_retains_prior_unwritten_values():
    """Requirement 10.6: final lookup failure preserves unwritten values."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-lf")] = {
        "id": "task-lf",
        "name": "anim",
        "data": {"kitsuId": "kt-task-lf"},
    }
    writer.tasks["kt-task-lf"] = {
        "id": "kt-task-lf",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }
    store.users = [
        {"name": "alice", "attrib": {"email": "alice@studio.com"}},
        {"name": "bob", "attrib": {"email": "bob@studio.com"}},
    ]
    writer.persons = [
        {"id": "p-alice", "name": "Alice", "email": "alice@studio.com"},
        {"id": "p-bob", "name": "Bob", "email": "bob@studio.com"},
    ]

    orig_assign = writer.assign

    def fail_bob(task, person_id):
        if person_id == "p-bob":
            raise KitsuWriterError("fail", "503", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_bob

    store.add_source_event(
        event_id="evt-lf-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={"newValue": ["alice", "bob"]},
        summary={"entityId": "task-lf"},
        user="coordinator",
    )

    runner.poll_once()
    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    assert job["summary"]["notWritten"] == {"assignees": ["Bob"]}

    # Advance clock past retry delay and make lookup fail permanently
    clock.advance(RETRY_DELAY_S + 5.0)
    writer.get_task = MagicMock(
        side_effect=KitsuWriterError(
            "not_found", "Task deleted", retryable=False
        )
    )

    runner.poll_once()
    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert job["summary"]["notWritten"] == {"assignees": ["Bob"]}
    assert "unwritten values: none" not in job["description"]
    assert "Bob" in job["description"]
    assert "assigned Alice" in job["description"]


def test_successful_retry_clears_stale_not_written():
    """Audit 5 item 2: successful retry clears stale notWritten."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-sr")] = {
        "id": "task-sr",
        "name": "comp",
        "data": {"kitsuId": "kt-task-sr"},
    }
    writer.tasks["kt-task-sr"] = {
        "id": "kt-task-sr",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }
    store.users = [
        {"name": "alice", "attrib": {"email": "alice@studio.com"}},
        {"name": "bob", "attrib": {"email": "bob@studio.com"}},
    ]
    writer.persons = [
        {"id": "p-alice", "name": "Alice", "email": "alice@studio.com"},
        {"id": "p-bob", "name": "Bob", "email": "bob@studio.com"},
    ]

    attempt_count = [0]
    orig_assign = writer.assign

    def fail_bob_first(task, person_id):
        if person_id == "p-bob" and attempt_count[0] == 0:
            attempt_count[0] += 1
            raise KitsuWriterError("fail", "503", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_bob_first

    store.add_source_event(
        event_id="evt-sr-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={"newValue": ["alice", "bob"]},
        summary={"entityId": "task-sr"},
        user="coordinator",
    )

    runner.poll_once()
    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    assert job["summary"]["notWritten"] == {"assignees": ["Bob"]}

    # Attempt 2: retry succeeds
    clock.advance(RETRY_DELAY_S + 5.0)
    runner.poll_once()
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert job["summary"].get("notWritten") is None
    assert "Applied:" in job["description"]
    assert "unwritten" not in job["description"].lower()


def test_assignee_mutation_records_preserve_snapshots_across_retries():
    """Requirement 13.2: mutation snapshots preserved across retries."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-ms")] = {
        "id": "task-ms",
        "name": "fx",
        "data": {"kitsuId": "kt-task-ms"},
    }
    writer.tasks["kt-task-ms"] = {
        "id": "kt-task-ms",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }
    store.users = [
        {"name": "alice", "attrib": {"email": "alice@studio.com"}},
        {"name": "bob", "attrib": {"email": "bob@studio.com"}},
    ]
    writer.persons = [
        {"id": "p-alice", "name": "Alice", "email": "alice@studio.com"},
        {"id": "p-bob", "name": "Bob", "email": "bob@studio.com"},
    ]

    attempt_count = [0]
    orig_assign = writer.assign

    def fail_bob_once(task, person_id):
        if person_id == "p-bob" and attempt_count[0] == 0:
            attempt_count[0] += 1
            raise KitsuWriterError("fail", "503", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_bob_once

    store.add_source_event(
        event_id="evt-ms-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={"newValue": ["alice", "bob"]},
        summary={"entityId": "task-ms"},
        user="coordinator",
    )

    runner.poll_once()
    job = store.jobs["job-1"]
    w1 = job["summary"]["writes"]
    assert len(w1) == 1
    assert w1[0]["person_name"] == "Alice"
    assert w1[0]["before"] == []
    assert w1[0]["sent"] == ["Alice"]

    # Attempt 2
    clock.advance(RETRY_DELAY_S + 5.0)
    runner.poll_once()
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "before: none" in job["description"]
    assert "sent: [Alice, Bob]" in job["description"]
    writes = job["summary"]["writes"]
    assert len(writes) == 2
    assert writes[0]["before"] == []
    assert writes[0]["sent"] == ["Alice"]
    assert writes[1]["before"] == ["Alice"]
    assert writes[1]["sent"] == ["Alice", "Bob"]


def test_mixed_attribute_outcome_retains_no_previous_value_on_conflict():
    """Requirement 9.6: mixed outcome retains no previous value on conflict."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("folder", "fold-mix")] = {
        "id": "fold-mix",
        "name": "shot07",
        "data": {"kitsuId": "kt-fold-mix"},
        "attrib": {"fps": 30.0, "description": "AYON new"},
        "ownAttrib": ["fps", "description"],
    }
    writer.tasks["kt-fold-mix"] = {
        "id": "kt-fold-mix",
        "type": "Shot",
        "project_id": "kitsu-proj-1",
        "description": "Kitsu current",
        "data": {"fps": 24.0},
    }

    store.add_source_event(
        event_id="evt-mix-1",
        topic=TOPIC_FOLDER_ATTRIB_CHANGED,
        project_name="test-project",
        created_at=1080.0,
        payload={
            "oldValue": {"description": "AYON old"},
            "newValue": {"fps": 30.0, "description": "AYON new"},
        },
        summary={"entityId": "fold-mix"},
        user="test-user",
    )

    ran = runner.poll_once()
    assert ran is True

    job = store.jobs["job-1"]
    assert "Conflict:" in job["description"]
    assert "no previous value for fps" in job["description"]
    assert len(writer.updated_fields) == 1
    assert writer.updated_fields[0]["fields"]["data.fps"] == 30.0


def test_fourth_attempt_failure_preserves_original_reason():
    """Requirement 10.6: attempt 4 failure retains original reason."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-fa")] = {
        "id": "task-fa",
        "name": "anim",
        "data": {"kitsuId": "kt-task-fa"},
    }
    writer.tasks["kt-task-fa"] = {
        "id": "kt-task-fa",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": [],
    }
    store.users = [
        {"name": "alice", "attrib": {"email": "alice@studio.com"}},
        {"name": "bob", "attrib": {"email": "bob@studio.com"}},
    ]
    writer.persons = [
        {"id": "p-alice", "name": "Alice", "email": "alice@studio.com"},
        {"id": "p-bob", "name": "Bob", "email": "bob@studio.com"},
    ]

    orig_assign = writer.assign

    def fail_bob(task, person_id):
        if person_id == "p-bob":
            raise KitsuWriterError("fail", "503", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_bob

    store.add_source_event(
        event_id="evt-fa-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={"newValue": ["alice", "bob"]},
        summary={"entityId": "task-fa"},
        user="coordinator",
    )

    # Attempt 1
    runner.poll_once()
    assert store.jobs["job-1"]["status"] == "pending"

    # Attempt 2
    clock.advance(RETRY_DELAY_S + 5.0)
    runner.poll_once()
    assert store.jobs["job-1"]["status"] == "pending"

    # Attempt 3
    clock.advance(RETRY_DELAY_S + 5.0)
    runner.poll_once()
    assert store.jobs["job-1"]["status"] == "pending"

    # Attempt 4: fails with Task deleted HTTP 404
    clock.advance(RETRY_DELAY_S + 5.0)
    writer.get_task = MagicMock(
        side_effect=KitsuWriterError(
            "not_found", "Task deleted", retryable=False, http_status=404
        )
    )
    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert "does not exist in Kitsu" in job["description"]
    assert "retry limit exceeded" in job["description"]
    assert "[HTTP 404]" in job["description"]
    assert "(attempt 4/4)" in job["description"]
    assert "Bob" in job["description"]
    assert "assigned Alice" in job["description"]


def test_unmanaged_assignee_preserved_across_retries_with_snapshots():
    """Requirement 13.2: unmanaged assignees tracked across retries."""
    clock, store, writer, runner = _setup_slice2_runner()

    store.entities[("task", "task-um")] = {
        "id": "task-um",
        "name": "comp",
        "data": {"kitsuId": "kt-task-um"},
    }
    writer.tasks["kt-task-um"] = {
        "id": "kt-task-um",
        "type": "Task",
        "project_id": "kitsu-proj-1",
        "assignees": ["p-unmanaged"],
    }
    store.users = [
        {"name": "alice", "attrib": {"email": "alice@studio.com"}},
        {"name": "bob", "attrib": {"email": "bob@studio.com"}},
    ]
    writer.persons = [
        {"id": "p-alice", "name": "Alice", "email": "alice@studio.com"},
        {"id": "p-bob", "name": "Bob", "email": "bob@studio.com"},
        {
            "id": "p-unmanaged",
            "name": "External",
            "email": "external@vendor.com",
        },
    ]

    attempt_count = [0]
    orig_assign = writer.assign

    def fail_bob_once(task, person_id):
        if person_id == "p-bob" and attempt_count[0] == 0:
            attempt_count[0] += 1
            raise KitsuWriterError("fail", "503", retryable=True)
        return orig_assign(task, person_id)

    writer.assign = fail_bob_once

    store.add_source_event(
        event_id="evt-um-1",
        topic=TOPIC_TASK_ASSIGNEES_CHANGED,
        project_name="test-project",
        created_at=1010.0,
        payload={"newValue": ["alice", "bob"]},
        summary={"entityId": "task-um"},
        user="coordinator",
    )

    # Attempt 1: Alice added alongside unmanaged External
    runner.poll_once()
    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    w1 = job["summary"]["writes"]
    assert len(w1) == 1
    assert w1[0]["before"] == ["External"]
    assert w1[0]["sent"] == ["Alice", "External"]

    # Attempt 2: Bob succeeds alongside Alice and External
    clock.advance(RETRY_DELAY_S + 5.0)
    runner.poll_once()
    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "before: [External]" in job["description"]
    assert "sent: [Alice, Bob, External]" in job["description"]
    assert "added assignees: [Alice, Bob]" in job["description"]
    writes = job["summary"]["writes"]
    assert len(writes) == 2
    assert writes[0]["before"] == ["External"]
    assert writes[0]["sent"] == ["Alice", "External"]
    assert writes[1]["before"] == ["Alice", "External"]
    assert writes[1]["sent"] == ["Alice", "Bob", "External"]
    assert "p-unmanaged" in writer.tasks["kt-task-um"]["assignees"]


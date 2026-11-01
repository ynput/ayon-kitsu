"""Unit tests for safeguards introduced from Codex reviews.

Validates:
- Defer inbound full syncs during startup drain (runner.py)
- In-flight creation coordination against inbound echo races
  (processor.py, creation.py, update_from_kitsu.py)
- Surviving AYON owners check before deleting Kitsu target (deletion.py)
- Status code & error validation on /kitsu-owners lookup (identity.py)
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from processor.outbound.constants import (
    DECISION_APPLIED,
    DECISION_FAILED,
    DECISION_SKIPPED,
    ERROR_UNREACHABLE,
    TOPIC_FOLDER_CREATED,
    TOPIC_FOLDER_DELETED,
)
from processor.outbound.handlers.attributes import handle_attributes
from processor.outbound.handlers.creation import handle_creation
from processor.outbound.handlers.deletion import handle_deletion
from processor.outbound.identity import IdentityResolver
from processor.outbound.runner import OutboundJobRunner
from processor.outbound.settings_watch import GateHistory, SettingsWatcher
from processor.processor import KitsuProcessor
import processor.update_from_kitsu as update_from_kitsu

from .offline import block_network  # noqa: F401
from .outbound_fakes import FakeAyonStore, FakeClock, FakeKitsuWriter

pytestmark = pytest.mark.usefixtures("block_network")

PROJECT = "test-project"
KITSU_PROJECT = "kitsu-proj-1"


def _setup_runner(enabled=True):
    """Build a runner with Slice 3 deletion enabled."""
    clock = FakeClock(1000.0)
    store = FakeAyonStore(clock=clock)
    writer = FakeKitsuWriter()

    sync_cfg = store.studio_settings["sync_settings"]["two_way_sync"]
    sync_cfg["entity_deletion"] = enabled

    processor = MagicMock()
    processor.sender = "kitsu-processor-test"
    processor.pairing_list = {PROJECT: KITSU_PROJECT}

    categories = {
        "task_status": True,
        "task_assignees": False,
        "entity_attributes": False,
        "entity_deletion": enabled,
    }
    gate_history = GateHistory(store, clock=clock)
    gate_history.record_observation(
        PROJECT,
        {
            "valid": True,
            "master": True,
            "categories": categories,
            "conflict_policy": "kitsu_wins",
        },
        now=clock(),
    )
    watcher = SettingsWatcher(
        store,
        pairing_list_getter=lambda: {PROJECT: KITSU_PROJECT},
        clock=clock,
        gate_history=gate_history,
    )
    watcher.refresh()
    runner = OutboundJobRunner(
        processor=processor,
        clock=clock,
        ayon_client=store,
        writer=writer,
        settings_watcher=watcher,
        gate_history=gate_history,
        identity_resolver=IdentityResolver(store, writer),
        sender="kitsu-processor-test",
    )
    return clock, store, writer, runner, processor


def _add_event(store, event_id, topic, entity_id, **kwargs):
    return store.add_source_event(
        event_id=event_id,
        topic=topic,
        project_name=PROJECT,
        created_at=kwargs.pop("created_at", 1010.0),
        summary={"entityId": entity_id},
        user="test-user",
        **kwargs,
    )


# ===========================================================================
# 1. Defer Inbound Sync Requests During Startup Drain
# ===========================================================================


def test_poll_inbound_sync_request_deferred_during_drain():
    """Requirement: defer inbound full syncs until drain completes."""
    _, _, _, runner, processor = _setup_runner()
    processor.poll_sync_request = MagicMock(return_value=True)

    # When in_drain is True, inbound sync polling is deferred
    runner.in_drain = True
    assert runner.poll_inbound_sync_request() is False
    assert processor.poll_sync_request.call_count == 0

    # When in_drain is False, inbound sync polling proceeds normally
    runner.in_drain = False
    assert runner.poll_inbound_sync_request() is True
    assert processor.poll_sync_request.call_count == 1


def test_drain_sets_and_clears_in_drain_flag():
    """drain() must set in_drain=True during drain and restore it to False."""
    _, store, _, runner, _ = _setup_runner()

    assert runner.in_drain is False
    observed_in_drain = []

    orig_enroll = runner._enroll

    def mock_enroll():
        observed_in_drain.append(runner.in_drain)
        return orig_enroll()

    with patch.object(runner, "_enroll", side_effect=mock_enroll):
        runner.drain()

    assert observed_in_drain == [True]
    assert runner.in_drain is False


def test_drain_clears_in_drain_on_exception():
    """drain() must reset in_drain to False even if an exception occurs."""
    _, _, _, runner, _ = _setup_runner()

    with patch.object(
        runner, "reap_stale", side_effect=RuntimeError("Simulated error")
    ):
        with pytest.raises(RuntimeError):
            runner.drain()

    assert runner.in_drain is False


# ===========================================================================
# 2. In-Flight Creation Coordination
# ===========================================================================


def test_in_flight_creation_methods_lifecycle():
    """Test register, wait, and finish lifecycle on KitsuProcessor."""
    # Test methods directly on an uninitialized instance to avoid ayon_api init
    proc = object.__new__(KitsuProcessor)
    proc.in_flight_creations = {}
    proc.in_flight_lock = threading.Lock()

    # When not registered, wait returns immediately True
    assert proc.wait_for_in_flight_creation("kt-123", timeout=0.1) is True

    # Register an in-flight creation
    ev = proc.register_in_flight_creation("kt-123")
    assert isinstance(ev, threading.Event)
    assert not ev.is_set()

    # Waiting should time out when not finished
    assert proc.wait_for_in_flight_creation("kt-123", timeout=0.05) is False

    # Finish releases the event and removes it from dict
    proc.finish_in_flight_creation("kt-123")
    assert ev.is_set()
    assert "kt-123" not in proc.in_flight_creations

    # Subsequent waits return immediately True
    assert proc.wait_for_in_flight_creation("kt-123", timeout=0.1) is True


def test_update_from_kitsu_calls_wait_for_in_flight():
    """Ensure update_from_kitsu functions wait for in-flight creations."""
    parent = MagicMock()
    # Early return after wait:
    parent.get_paired_ayon_project.return_value = None

    update_from_kitsu.create_or_update_asset(
        parent, {"asset_id": "ast-1", "project_id": "p1"}
    )
    parent.wait_for_in_flight_creation.assert_called_with("ast-1")

    update_from_kitsu.create_or_update_episode(
        parent, {"episode_id": "ep-1", "project_id": "p1"}
    )
    parent.wait_for_in_flight_creation.assert_called_with("ep-1")

    update_from_kitsu.create_or_update_sequence(
        parent, {"sequence_id": "sq-1", "project_id": "p1"}
    )
    parent.wait_for_in_flight_creation.assert_called_with("sq-1")

    update_from_kitsu.create_or_update_shot(
        parent, {"shot_id": "sh-1", "project_id": "p1"}
    )
    parent.wait_for_in_flight_creation.assert_called_with("sh-1")


# ===========================================================================
# 3. Surviving AYON Owners Guard for Deletions
# ===========================================================================


def test_deletion_skipped_when_surviving_owner_exists():
    """Deletion must be skipped if another AYON entity owns the kitsuId."""
    _, store, writer, runner, _ = _setup_runner()

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

    _add_event(
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
    _, store, writer, runner, _ = _setup_runner()

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
    _add_event(
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


# ===========================================================================
# 4. /kitsu-owners HTTP Error and Validation Handling
# ===========================================================================


def test_kitsu_owners_http_error_raises_runtime_error():
    """HTTP status >= 400 from /kitsu-owners must raise RuntimeError."""
    store = FakeAyonStore()
    writer = FakeKitsuWriter()
    resolver = IdentityResolver(store, writer)

    error_resp = MagicMock()
    error_resp.status_code = 503
    error_resp.data = {"detail": "Service Unavailable"}

    with patch.object(store, "get", return_value=error_resp):
        with pytest.raises(RuntimeError, match="HTTP 503"):
            resolver.get_kitsu_owners("test-project", "kt-123")


def test_kitsu_owners_error_detail_raises_runtime_error():
    """Response dict containing 'detail' without 'folders' raises error."""
    store = FakeAyonStore()
    writer = FakeKitsuWriter()
    resolver = IdentityResolver(store, writer)

    error_dict = {"detail": "Internal server error during lookup"}
    with patch.object(store, "get", return_value=error_dict):
        with pytest.raises(RuntimeError, match="Internal server error"):
            resolver.get_kitsu_owners("test-project", "kt-123")


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


def test_creation_inbound_protected_before_post_response():
    """Inbound callbacks during Kitsu POST must wait on in-flight creation."""
    proc = object.__new__(KitsuProcessor)
    proc.in_flight_creations = {}
    proc.in_flight_lock = threading.Lock()
    proc._active_creation_event = None

    observed_active_during_post = []
    writer = FakeKitsuWriter()

    def mock_create_entity(**kw):
        # Inbound callback arrives while HTTP POST is executing:
        active = proc.wait_for_in_flight_creation("kt-new", timeout=0.01)
        observed_active_during_post.append(active)
        return {"id": "kt-new"}

    writer.create_entity = mock_create_entity

    resolver = MagicMock()

    def mock_get_ayon_entity(proj, kind, eid):
        if eid == "fold-seq":
            return {
                "id": "fold-seq",
                "name": "sq010",
                "folderType": "Sequence",
                "data": {"kitsuId": "kt-seq-1"},
            }
        return {
            "id": "fold-new",
            "name": "sh020",
            "folderType": "Shot",
            "parentId": "fold-seq",
            "data": {},
        }

    resolver.get_ayon_entity.side_effect = mock_get_ayon_entity
    resolver.ayon_client = MagicMock()

    ctx = MagicMock()
    ctx.event = {
        "topic": TOPIC_FOLDER_CREATED,
        "payload": {
            "entityData": {
                "id": "fold-new",
                "name": "sh020",
                "folderType": "Shot",
                "parentId": "fold-seq",
            }
        },
    }
    ctx.entity_id = "fold-new"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.processor = proc
    ctx.attempt = 1
    ctx.loop_guard_check.return_value = {"allowed": True}

    writer.tasks["kt-seq-1"] = {
        "id": "kt-seq-1",
        "type": "Sequence",
        "name": "sq010",
        "project_id": KITSU_PROJECT,
    }
    resolver.get_parent_entity.return_value = {
        "id": "fold-seq",
        "folderType": "Sequence",
        "data": {"kitsuId": "kt-seq-1"},
    }

    res = handle_creation(ctx)
    assert res.decision == "applied"
    # During POST, inbound wait returned False (blocked by timeout):
    assert observed_active_during_post == [False]
    # After creation finishes, active creation is cleared:
    assert proc.wait_for_in_flight_creation("kt-new", timeout=0.01) is True


def test_runner_retries_transient_source_event_fetch_error():
    """Transient exception fetching source event must be retryable."""
    _, store, _, runner, _ = _setup_runner()

    store.add_source_event(
        event_id="evt-source",
        topic="entity.task.status_changed",
        project_name=PROJECT,
        created_at=1010.0,
        summary={"taskId": "task-1"},
        user="test-user",
    )

    with patch.object(
        store, "get_event", side_effect=RuntimeError("AYON 503 error")
    ):
        runner.poll_once()

    assert len(store.jobs) == 1
    stored_job = next(iter(store.jobs.values()))
    assert stored_job["status"] == "pending"
    assert stored_job["summary"]["attempt"] == 1
    assert runner.held_job is not None
    desc = stored_job["description"]
    assert "Transient error fetching source event" in desc


def test_gate_history_retries_unpersisted_snapshots():
    """GateHistory retries failed snapshots on subsequent observation."""
    store = FakeAyonStore()
    clock = FakeClock(1000.0)
    gh = GateHistory(store, clock=clock)

    # First call: dispatch_event raises an exception
    with patch.object(
        store, "dispatch_event", side_effect=RuntimeError("Network error")
    ):
        res = gh.record_observation(
            PROJECT, {"valid": True, "master": True}, now=1000.0
        )
        assert res is None
        assert PROJECT in gh.unpersisted_snapshots

    # Second call with same toggles: dispatch succeeds
    res2 = gh.record_observation(
        PROJECT, {"valid": True, "master": True}, now=1010.0
    )
    assert res2 is not None
    assert PROJECT not in gh.unpersisted_snapshots


def test_update_from_kitsu_timeout_defers_push():
    """When wait_for_in_flight_creation times out, push is deferred."""
    proc = MagicMock()
    proc.wait_for_in_flight_creation.return_value = False
    proc.get_paired_ayon_project.return_value = PROJECT
    proc.entrypoint = f"/addons/kitsu/{PROJECT}"

    with patch("processor.update_from_kitsu.ayon_api.post") as mock_post:
        # Asset
        res_asset = update_from_kitsu.create_or_update_asset(
            proc, {"asset_id": "ast-1", "project_id": KITSU_PROJECT}
        )
        assert res_asset is None

        # Episode
        res_ep = update_from_kitsu.create_or_update_episode(
            proc, {"episode_id": "ep-1", "project_id": KITSU_PROJECT}
        )
        assert res_ep is None

        # Sequence
        res_seq = update_from_kitsu.create_or_update_sequence(
            proc, {"sequence_id": "sq-1", "project_id": KITSU_PROJECT}
        )
        assert res_seq is None

        # Shot
        res_shot = update_from_kitsu.create_or_update_shot(
            proc, {"shot_id": "sh-1", "project_id": KITSU_PROJECT}
        )
        assert res_shot is None

        # Task
        res_task = update_from_kitsu.create_or_update_task(
            proc, {"task_id": "tk-1", "project_id": KITSU_PROJECT}
        )
        assert res_task is None

        mock_post.assert_not_called()


def test_attributes_inherited_fps_reset_skipped():
    """Resetting fps to inherited (None) must not write to Kitsu."""
    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
        "data": {"fps": "24"},
    }

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": {"id": "kt-shot-1"},
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {"fps": 24.0},
            "own_attributes": {"fps": None},
        },
    }

    ctx = MagicMock()
    ctx.event = {
        "topic": "entity.folder.attrib_changed",
        "payload": {
            "changed": {"fps": None},
            "oldValue": {"fps": 25.0},
        },
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.attempt = 1
    ctx.prior_writes = []

    res = handle_attributes(ctx)
    assert res.decision == DECISION_SKIPPED
    assert "skipped because inherited: fps" in res.description
    assert len(writer.updated_fields) == 0


def test_runner_retry_preserves_source_event_id():
    """Transient fetch error preserves dependsOn in runner.held_job."""
    _, store, _, runner, _ = _setup_runner()

    store.add_source_event(
        event_id="evt-source-123",
        topic="entity.task.status_changed",
        project_name=PROJECT,
        created_at=1010.0,
        summary={"taskId": "task-1"},
        user="test-user",
    )

    with patch.object(
        store, "get_event", side_effect=RuntimeError("AYON 503 error")
    ):
        runner.poll_once()

    assert runner.held_job is not None
    assert runner.held_job["job"]["dependsOn"] == "evt-source-123"
    assert runner.held_job["job"]["summary"]["sourceEventId"] == (
        "evt-source-123"
    )


def test_settings_watcher_project_aware_api_signature():
    """SettingsWatcher must use project-aware API without raising TypeError."""
    mock_client = MagicMock()

    def mock_get_service():
        return {
            "sync_settings": {
                "two_way_sync": {
                    "enabled": True,
                    "task_status": True,
                    "task_assignees": False,
                    "entity_attributes": False,
                    "entity_creation": False,
                    "entity_rename": False,
                    "entity_deletion": False,
                    "conflict_policy": "kitsu_wins",
                }
            }
        }

    mock_client.get_service_addon_settings.side_effect = (
        lambda *args, **kwargs: (
            mock_get_service()
            if not args and not kwargs
            else (_ for _ in ()).throw(
                TypeError("get_service_addon_settings() takes 0 arguments")
            )
        )
    )
    mock_client.get_service_addon_name.return_value = "kitsu"
    mock_client.get_service_addon_version.return_value = "1.2.4"
    mock_client.get_addon_project_settings.return_value = {}

    watcher = SettingsWatcher(
        mock_client,
        pairing_list_getter=lambda: {PROJECT: KITSU_PROJECT},
    )
    effective = watcher.refresh()
    assert PROJECT in effective
    assert effective[PROJECT]["valid"] is True
    assert effective[PROJECT]["master"] is True
    mock_client.get_addon_project_settings.assert_called_with(
        "kitsu", "1.2.4", PROJECT
    )


def test_gate_history_newest_first_preserves_latest_snapshot():
    """Gate events loaded newest-first must not suppress changes."""
    store = FakeAyonStore()
    clock = FakeClock(1000.0)
    gh = GateHistory(store, clock=clock)

    newer_event = {
        "id": "gate-evt-2",
        "topic": "kitsu.gate",
        "createdAt": 1020.0,
        "summary": {
            "project": PROJECT,
            "toggles": {"valid": True, "master": True},
            "observedAt": 1020.0,
        },
    }
    older_event = {
        "id": "gate-evt-1",
        "topic": "kitsu.gate",
        "createdAt": 1010.0,
        "summary": {
            "project": PROJECT,
            "toggles": {"valid": True, "master": False},
            "observedAt": 1010.0,
        },
    }
    store.other_events = [newer_event, older_event]
    gh.load(started_at=1030.0)

    ev_id = gh.record_observation(
        PROJECT, {"valid": True, "master": False}, now=1040.0
    )
    assert ev_id is not None
    latest = max(
        gh.history[PROJECT],
        key=lambda s: s.get("observedAt", 0.0),
    )
    assert latest["toggles"]["master"] is False
    assert latest["observedAt"] == 1040.0


def test_attributes_unchanged_counterpart_preserved():
    """When counterpart in Kitsu conflicts, protect from overwrite."""
    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
        "data": {"frame_in": 1001, "frame_out": 1200},
        "nb_frames": 200,
    }

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": {"id": "kt-shot-1"},
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {"frameStart": 1002, "frameEnd": 1100},
            "own_attributes": ["frameStart", "frameEnd"],
        },
    }

    ctx = MagicMock()
    ctx.event = {
        "topic": "entity.folder.attrib_changed",
        "payload": {
            "changed": {"frameStart": 1002},
            "oldValue": {"frameStart": 1001, "frameEnd": 1100},
        },
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.conflict_policy = "kitsu_wins"
    ctx.processor = MagicMock()
    ctx.loop_guard_check.return_value = {"allowed": True}
    ctx.attempt = 1
    ctx.prior_writes = []

    res = handle_attributes(ctx)
    assert res.decision == "conflict"
    for update in writer.updated_fields:
        assert "data.frame_out" not in update["fields"]


def test_task_attribute_conflict_restored_under_kitsu_wins():
    """Task attribute conflict under kitsu_wins restores AYON attribute."""
    writer = FakeKitsuWriter()
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "type": "Task",
        "name": "animation",
        "project_id": KITSU_PROJECT,
        "data": {"fps": 24.0},
    }

    store = FakeAyonStore()
    store.update_task = MagicMock()

    resolver = MagicMock()
    resolver.ayon_client = store
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": {"id": "kt-task-1"},
        "ayon": {
            "id": "task-1",
            "name": "animation",
            "taskType": "Animation",
            "attrib": {"fps": 30.0},
            "own_attributes": ["fps"],
        },
    }

    ctx = MagicMock()
    ctx.event = {
        "topic": "entity.task.attrib_changed",
        "payload": {
            "changed": {"fps": 30.0},
            "oldValue": {"fps": 25.0},
        },
    }
    ctx.entity_id = "task-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.conflict_policy = "kitsu_wins"
    ctx.processor = MagicMock()
    ctx.attempt = 1
    ctx.prior_writes = []

    res = handle_attributes(ctx)
    assert res.decision == "conflict"
    store.update_task.assert_called_with(
        project_name=PROJECT,
        task_id="task-1",
        attrib={"fps": 24.0},
    )


def test_get_events_explicit_fields_with_summary():
    """Ensure get_events queries pass explicit fields with summary."""
    mock_client = MagicMock()
    mock_client.get_events.return_value = []
    clock = FakeClock(1000.0)

    # 1. GateHistory.load() queries gate events and settings.changed
    gh = GateHistory(mock_client, clock=clock)
    gh.load(started_at=1000.0)
    assert mock_client.get_events.call_count == 2
    call_gate = mock_client.get_events.call_args_list[0]
    call_ch = mock_client.get_events.call_args_list[1]
    assert "summary" in call_gate.kwargs.get("fields", [])
    assert "summary" in call_ch.kwargs.get("fields", [])

    # 2. OutboundJobRunner queries
    _, _, _, runner, _ = _setup_runner(enabled=True)
    runner.ayon_client = mock_client
    mock_client.get_events.reset_mock()

    runner.recover_interrupted()
    assert mock_client.get_events.called
    assert "summary" in mock_client.get_events.call_args.kwargs.get(
        "fields", []
    )

    mock_client.get_events.reset_mock()
    runner.reap_stale()
    assert mock_client.get_events.called
    assert "summary" in mock_client.get_events.call_args.kwargs.get(
        "fields", []
    )


def test_attributes_loop_guard_atomic_frame_range_suppression():
    """Paired frame fields are atomically suppressed if any loops."""
    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
        "data": {"frame_in": 1001, "frame_out": 1100},
        "nb_frames": 100,
    }

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": {"id": "kt-shot-1"},
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {"frameStart": 1005, "frameEnd": 1120},
            "own_attributes": ["frameStart", "frameEnd"],
        },
    }

    ctx = MagicMock()
    ctx.event = {
        "topic": "entity.folder.attrib_changed",
        "payload": {
            "changed": {"frameStart": 1005, "frameEnd": 1120},
            "oldValue": {"frameStart": 1001, "frameEnd": 1100},
        },
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.conflict_policy = "ayon_wins"
    ctx.processor = MagicMock()
    # Reject frame_in, but allow other fields
    ctx.loop_guard_check.side_effect = (
        lambda ent, fld: {"allowed": False}
        if fld == "data.frame_in"
        else {"allowed": True}
    )
    ctx.attempt = 1
    ctx.prior_writes = []

    res = handle_attributes(ctx)
    assert res.decision == DECISION_SKIPPED
    assert "loop suspected" in res.description
    assert len(writer.updated_fields) == 0


def test_inbound_empty_description_parsed():
    """Empty description from Kitsu is parsed and preserved as empty."""
    from attrib_parsing import parse_attrib

    # Emulate sync_task / sync_folder boundary
    entity_dict = {"description": ""}
    data = {}
    if "description" in entity_dict:
        data["description"] = entity_dict["description"] or ""

    assert data["description"] == ""
    parsed = parse_attrib(data)
    assert parsed.get("description") == ""


def test_gate_history_load_failure_raises_runtime_error():
    """GateHistory.load() raises RuntimeError when get_events fails."""
    mock_client = MagicMock()
    mock_client.get_events.side_effect = RuntimeError("AYON connection failed")
    clock = FakeClock(100.0)
    gh = GateHistory(mock_client, clock=clock)

    with pytest.raises(RuntimeError) as exc_info:
        gh.load(started_at=100.0)
    assert "Could not load gate events" in str(exc_info.value)


def test_kitsu_attrib_view_preserves_empty_description():
    """kitsu_attrib_view preserves empty string descriptions."""
    from processor.outbound.mapping import kitsu_attrib_view

    view1 = kitsu_attrib_view({"description": "", "data": {}})
    assert view1.get("description") == ""

    view2 = kitsu_attrib_view({"description": None, "data": {}})
    assert view2.get("description") == ""

    view3 = kitsu_attrib_view({"data": {}})
    assert "description" not in view3


def test_inbound_creation_timeout_queues_and_replays():
    """Inbound callback is queued on creation wait timeout and replayed."""
    from processor.processor import KitsuProcessor
    from processor.update_from_kitsu import create_or_update_asset

    proc = MagicMock(spec=KitsuProcessor)
    proc.deferred_inbound_events = []
    proc.deferred_inbound_lock = threading.Lock()
    proc.defer_inbound_call = (
        lambda func, *args, **kwargs:
            KitsuProcessor.defer_inbound_call(proc, func, *args, **kwargs)
    )
    proc.process_deferred_inbound_events = (
        lambda: KitsuProcessor.process_deferred_inbound_events(proc)
    )
    proc.wait_for_in_flight_creation.return_value = False

    data = {"asset_id": "ast-1", "project_id": "prj-1"}
    ret = create_or_update_asset(proc, data)
    assert ret is None
    assert len(proc.deferred_inbound_events) == 1

    # Replay
    executed = []

    def fake_func(parent, d):
        executed.append(d["asset_id"])

    proc.deferred_inbound_events = [(fake_func, (proc, data), {})]
    count = proc.process_deferred_inbound_events()
    assert count == 1
    assert executed == ["ast-1"]
    assert len(proc.deferred_inbound_events) == 0


def test_supersession_derived_fields_and_partial_attributes_omission():
    """Supersession checks category fields and omits partial attributes."""
    from processor.outbound.runner import _retried_fields_for_job

    assert _retried_fields_for_job("task_status", None) == ["task_status_id"]
    assert _retried_fields_for_job("task_assignees", None) == ["assignees"]
    assert _retried_fields_for_job("entity_rename", None) == ["name"]
    assert _retried_fields_for_job("entity_deletion", None) == [
        "deleted", "deletion"
    ]
    assert _retried_fields_for_job("entity_creation", None) == [
        "kitsuId", "creation"
    ]

    ev = {
        "payload": {
            "changed": {"fps": 24.0, "description": "new shot desc"}
        }
    }
    attrib_fields = _retried_fields_for_job("entity_attributes", ev)
    assert "data.fps" in attrib_fields
    assert "description" in attrib_fields

    # Partial omission in handle_attributes
    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "name": "sh010",
        "type": "Shot",
        "project_id": KITSU_PROJECT,
        "data": {"fps": 25.0},
        "description": "old desc",
    }

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": {"id": "kt-shot-1"},
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {"fps": 24.0, "description": "new desc"},
            "own_attributes": ["fps", "description"],
        },
    }

    ctx = MagicMock()
    ctx.event = {
        "topic": "entity.folder.attrib_changed",
        "payload": {
            "changed": {"fps": 24.0, "description": "new desc"},
            "oldValue": {"fps": 25.0, "description": "old desc"},
        },
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.conflict_policy = "ayon_wins"
    ctx.processor = MagicMock()
    ctx.loop_guard_check.return_value = {"allowed": True}
    ctx.attempt = 2
    ctx.prior_writes = []
    # Description was superseded by a newer applied job
    ctx.omitted_fields = ["description"]

    res = handle_attributes(ctx)
    assert res.decision == DECISION_APPLIED
    # Only data.fps was updated in Kitsu, description was omitted
    assert len(writer.updated_fields) == 1
    updated = writer.updated_fields[0]["fields"]
    assert "data.fps" in updated
    assert "description" not in updated


def test_drain_aborts_on_enroll_server_error():
    """Server errors (HTTP >= 500) during enroll must abort drain."""
    clock, store, writer, runner, _ = _setup_runner(enabled=True)
    resp = MagicMock()
    resp.status_code = 503
    resp.data = None
    store.post = MagicMock(return_value=resp)

    with pytest.raises(RuntimeError) as exc_info:
        runner.drain()

    assert "Enroll failed during drain" in str(exc_info.value)
    assert runner.last_enroll_error is not None
    assert "HTTP 503" in str(runner.last_enroll_error)


def test_enroll_filter_rejected_retries_without_filter_on_400():
    """HTTP 400 rejection on events_filter retries without filter."""
    clock, store, writer, runner, _ = _setup_runner(enabled=True)
    runner.enroll_filter_supported = True

    resp_400 = MagicMock()
    resp_400.status_code = 400
    resp_400.data = None

    resp_204 = MagicMock()
    resp_204.status_code = 204
    resp_204.data = None

    store.post = MagicMock(side_effect=[resp_400, resp_204])

    res = runner.poll_once()
    assert res is False
    assert runner.enroll_filter_supported is False
    assert runner.last_enroll_error is None
    assert store.post.call_count == 2
    # First call had filter, second call omitted filter
    first_call_kwargs = store.post.call_args_list[0][1]
    second_call_kwargs = store.post.call_args_list[1][1]
    assert "filter" in first_call_kwargs
    assert "filter" not in second_call_kwargs


def test_poll_once_fetches_full_job_metadata_preserving_retry():
    """Re-enrolling minimal job fetches full metadata and preserves retry."""
    clock, store, writer, runner, _ = _setup_runner(enabled=True)

    # Minimal enroll response
    resp_enroll = MagicMock()
    resp_enroll.status_code = 200
    resp_enroll.data = {
        "id": "job-retried",
        "dependsOn": "src-1",
        "status": "pending",
    }
    store.post = MagicMock(return_value=resp_enroll)

    # Full event returned by get_event
    store.get_event = MagicMock(
        return_value={
            "id": "job-retried",
            "depends_on": "src-1",
            "status": "pending",
            "sender": runner.sender,
            "project": PROJECT,
            "summary": {
                "attempt": 2,
                "lastFailedAt": 995.0,
                "writes": ["shot"],
            },
        }
    )

    # At now=1000.0, lastFailedAt=995.0; retry not due yet (< 10s delay)
    res = runner.poll_once()
    assert res is False
    assert runner.held_job is not None
    assert runner.held_job["attempt"] == 3
    assert runner.held_job["last_failed_at"] == 995.0
    held_summary = runner.held_job["job"]["summary"]
    assert held_summary.get("writes") == ["shot"]


def test_transient_source_fetch_failure_allows_attempt_4():
    """Attempt 3 transient source fetch failure holds for attempt 4."""
    clock, store, writer, runner, _ = _setup_runner(enabled=True)
    # Add a job that has attempt=3
    store.jobs["job-att3"] = {
        "id": "job-att3",
        "dependsOn": "src-missing",
        "topic": runner.TARGET_TOPIC,
        "sender": runner.sender,
        "status": "pending",
        "summary": {"attempt": 3},
        "createdAt": 1000.0,
    }
    # Simulate transient error fetching source event
    store.get_event = MagicMock(
        side_effect=RuntimeError("Transient DB timeout")
    )
    res = runner._process_job(store.jobs["job-att3"], attempt=3)
    # Must hold for attempt 4 instead of finishing as final failure
    assert res is True
    assert runner.held_job is not None
    assert runner.held_job["attempt"] == 4
    assert runner.held_job["job"]["id"] == "job-att3"


def test_drain_backs_off_on_pending_ayon_update(monkeypatch):
    """Pending AYON update during drain backs off instead of busy-spinning."""
    clock, store, writer, runner, _ = _setup_runner(enabled=True)
    runner.pending_ayon_update = {"job_id": "job-1", "status": "finished"}

    sleep_calls = []
    monkeypatch.setattr(
        "processor.outbound.runner.time.sleep",
        lambda s: sleep_calls.append(s),
    )

    # Fail the update 3 times, then succeed on 4th
    attempts = 0

    def mock_update(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise RuntimeError("AYON server 503")
        return None

    store.update_event = mock_update

    runner.drain()
    assert len(sleep_calls) >= 3
    assert sleep_calls[0] == 0.1  # 0.05 * 2^1
    assert sleep_calls[1] == 0.2  # 0.05 * 2^2
    assert runner.pending_ayon_update is None


def test_retry_pending_ayon_update_preserves_terminal_retries():
    """Pending AYON update retains terminal retries count upon replay."""
    from processor.outbound.constants import FINAL_RETRIES_VALUE

    clock, store, writer, runner, _ = _setup_runner(enabled=True)
    update_calls = []

    def mock_update(job_id, **kwargs):
        update_calls.append(dict(kwargs))
        if len(update_calls) < 3:
            raise RuntimeError("Transient AYON 503")
        return None

    runner.ayon_client.update_event = mock_update

    # Initial safe update fails and enters pending_ayon_update
    runner._update_event_safe(
        "job-term",
        status="failed",
        description="Non-retryable failure",
        retries=FINAL_RETRIES_VALUE,
        project_name=PROJECT,
    )

    assert runner.pending_ayon_update is not None
    assert runner.pending_ayon_update["_delivery_retries"] == 0
    assert (
        runner.pending_ayon_update["kwargs"]["retries"] == FINAL_RETRIES_VALUE
    )

    # First retry fails
    success = runner.retry_pending_ayon_update()
    assert success is False
    assert runner.pending_ayon_update is not None
    assert runner.pending_ayon_update["_delivery_retries"] == 1
    assert (
        runner.pending_ayon_update["kwargs"]["retries"] == FINAL_RETRIES_VALUE
    )
    assert update_calls[0]["retries"] == FINAL_RETRIES_VALUE
    assert update_calls[1]["retries"] == FINAL_RETRIES_VALUE

    # Second retry succeeds, still passing FINAL_RETRIES_VALUE
    success = runner.retry_pending_ayon_update()
    assert success is True
    assert runner.pending_ayon_update is None
    assert len(update_calls) == 3
    assert update_calls[2]["retries"] == FINAL_RETRIES_VALUE


def test_get_user_by_kitsu_id_propagates_non_not_found_errors():
    """get_user_by_kitsu_id raises on transient DB error,
    and returns None on 404.
    """
    import sys
    import types

    def run_coro(coro):
        try:
            coro.send(None)
        except StopIteration as exc:
            return exc.value

    for p in [
        "ayon_server",
        "ayon_server.api",
        "ayon_server.lib",
        "ayon_server.auth",
    ]:
        if p not in sys.modules:
            m = types.ModuleType(p)
            m.__path__ = []
            sys.modules[p] = m

    for sub in [
        "ayon_server.entities",
        "ayon_server.events",
        "ayon_server.lib.postgres",
        "ayon_server.types",
        "ayon_server.auth.session",
        "ayon_server.api.context",
        "ayon_server.exceptions",
    ]:
        if sub not in sys.modules:
            sys.modules[sub] = MagicMock()

    class AyonNotFound(Exception):
        pass

    sys.modules["ayon_server.exceptions"].NotFoundException = AyonNotFound

    if "server" not in sys.modules:
        server_mod = types.ModuleType("server")
        server_mod.__path__ = ["server"]
        sys.modules["server"] = server_mod

    if "server.kitsu" not in sys.modules:
        kitsu_mod = types.ModuleType("server.kitsu")
        kitsu_mod.__path__ = ["server/kitsu"]
        sys.modules["server.kitsu"] = kitsu_mod
        sys.modules["server"].kitsu = kitsu_mod

    import server.kitsu.attrib_parsing  # noqa: F401
    import server.kitsu.constants  # noqa: F401
    import server.kitsu.utils as kitsu_utils

    class CustomNotFound(Exception):
        status_code = 404

    # 1. DB returns user row, but UserEntity.load raises transient DB error
    async def mock_fetch(*args, **kwargs):
        return [{"name": "alice"}]

    kitsu_utils.Postgres.fetch = mock_fetch

    async def mock_load_err(name):
        raise RuntimeError("Transient DB connection loss")

    kitsu_utils.UserEntity.load = mock_load_err

    with pytest.raises(RuntimeError, match="Transient DB connection loss"):
        run_coro(kitsu_utils.get_user_by_kitsu_id("kitsu-u1"))

    # 2. When UserEntity.load raises 404 / NotFound, returns None
    async def mock_load_404(name):
        raise CustomNotFound("User not found")

    kitsu_utils.UserEntity.load = mock_load_404
    result = run_coro(kitsu_utils.get_user_by_kitsu_id("kitsu-u1"))
    assert result is None
def test_startup_full_sync_blocked_when_toggle_state_unknown(monkeypatch):
    """Full sync is blocked if gate_history.load fails and toggles unknown.
    """
    from .test_outbound_main_loop import (
        StopLoop,
        _setup_processor_harness,
    )

    proc, store, writer, clock = _setup_processor_harness()
    proc.pairing_list = {"kitsu-p1": "proj1"}

    # Simulate gate_history.load failure
    def fake_load(*args, **kwargs):
        raise RuntimeError("Events endpoint unavailable")

    monkeypatch.setattr(proc.outbound.gate_history, "load", fake_load)

    # Clear effective toggles so state is unknown
    proc.outbound.settings_watcher.effective_by_project.clear()

    def fake_refresh(*args, **kwargs):
        raise RuntimeError("Settings endpoint unavailable")

    monkeypatch.setattr(
        proc.outbound.settings_watcher, "refresh", fake_refresh
    )

    full_sync_calls = []

    def fake_full_sync(processor, project_id, project_name):
        full_sync_calls.append((project_id, project_name))

    def fake_sleep(secs):
        raise StopLoop()

    monkeypatch.setattr(
        "processor.processor.project_full_sync", fake_full_sync
    )
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)

    with pytest.raises(StopLoop):
        proc.start_processing()

    # Full sync should have been blocked because toggle state is unknown
    assert full_sync_calls == []
def test_startup_full_sync_blocked_when_settings_invalid(monkeypatch):
    """Full sync is blocked if refresh succeeds but effective toggles invalid.
    """
    from .test_outbound_main_loop import (
        StopLoop,
        _setup_processor_harness,
    )

    proc, store, writer, clock = _setup_processor_harness()
    proc.pairing_list = {"kitsu-p1": "proj1"}

    # Mock refresh to populate invalid toggles (e.g. read_failed=True)
    def fake_refresh(*args, **kwargs):
        proc.outbound.settings_watcher.effective_by_project["proj1"] = {
            "valid": False,
            "error": "Failed to read project settings",
            "master": False,
        }
        return proc.outbound.settings_watcher.effective_by_project

    monkeypatch.setattr(
        proc.outbound.settings_watcher, "refresh", fake_refresh
    )

    full_sync_calls = []

    def fake_full_sync(processor, project_id, project_name):
        full_sync_calls.append((project_id, project_name))

    def fake_sleep(secs):
        raise StopLoop()

    monkeypatch.setattr(
        "processor.processor.project_full_sync", fake_full_sync
    )
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)

    with pytest.raises(StopLoop):
        proc.start_processing()

    # Full sync blocked because effective settings are invalid
    assert full_sync_calls == []


def test_reaped_abandoned_job_transfers_ownership_and_unblocks_enroll():
    """Reaped foreign abandoned job transfers sender and unblocks enrollment.
    """
    clock = FakeClock(1000.0)
    store = FakeAyonStore(clock=clock)
    writer = FakeKitsuWriter()
    processor = MagicMock()
    processor.sender = "processor-B"
    processor.pairing_list = {PROJECT: KITSU_PROJECT}

    runner = OutboundJobRunner(
        processor=processor,
        clock=clock,
        ayon_client=store,
        writer=writer,
        sender="processor-B",
    )

    # 1. Add source event
    store.add_source_event(
        event_id="src-reap-1",
        topic="entity.task.status_changed",
        project_name=PROJECT,
        created_at=500.0,
    )

    # 2. Foreign processor-A enrolls it, goes in_progress, then dies
    job_a = store.enroll_event_job(
        source_topic="entity.task.status_changed",
        target_topic="kitsu.outbound_sync",
        sender="processor-A",
        sequential=True,
    )
    assert job_a is not None
    store.update_event(
        job_a["id"], status="in_progress", sender="processor-A"
    )

    # 3. Time advances > 300s (stale threshold)
    clock.advance(350.0)

    # 4. Processor B reaps stale jobs
    runner.reap_stale()

    reaped_job = store.jobs[job_a["id"]]
    assert reaped_job["status"] == "failed"
    # Ownership transferred to processor-B
    assert reaped_job["sender"] == "processor-B"

    # 5. Processor B calls _enroll() and successfully reclaims the job
    enrolled = runner._enroll()
    assert enrolled is not None
    assert enrolled["id"] == job_a["id"]
    assert enrolled["sender"] == "processor-B"
    assert enrolled["status"] == "pending"


def test_transient_ayon_entity_read_failure_holds_for_retry():
    """Transient error reading AYON entity in resolve() holds job for retry."""
    clock, store, writer, runner, _ = _setup_runner(enabled=True)
    store.add_source_event(
        event_id="transient-read",
        topic="entity.task.status_changed",
        project_name=PROJECT,
        created_at=1010.0,
        summary={"entityId": "t1"},
        user="artist",
        payload={"oldValue": "Todo", "newValue": "Done"},
    )

    def temporary_failure(*args, **kwargs):
        raise ConnectionError("temporary read outage")

    store.get_task_by_id = temporary_failure

    runner.poll_once()

    assert runner.held_job is not None
    assert runner.held_job["attempt"] == 2
    job = list(store.jobs.values())[0]
    assert job["status"] == "pending"
    assert job["retries"] == 0


def test_heartbeat_kept_behind_unpersisted_toggle_snapshot():
    """Heartbeat does not advance lastObservedAt past unpersisted snapshot."""
    clock = FakeClock(1000.0)
    store = FakeAyonStore(clock=clock)
    gh = GateHistory(store, clock=clock)

    # 1. Initial enabled=True snapshot persisted at t=1000
    ev1 = gh.record_observation(
        PROJECT, {"valid": True, "master": True}, now=1000.0
    )
    assert ev1 is not None
    assert gh.last_observed_at == 1000.0

    # 2. At t=1050 settings.changed occurs; at t=1060 dispatch_event fails
    store.other_events.append(
        {
            "id": "sc-1",
            "topic": "settings.changed",
            "createdAt": 1050.0,
            "summary": {"addon_name": "kitsu"},
        }
    )
    orig_dispatch = store.dispatch_event

    def fail_dispatch(*args, **kwargs):
        raise RuntimeError("Transient AYON dispatch failure")

    store.dispatch_event = fail_dispatch

    ev2 = gh.record_observation(
        PROJECT, {"valid": True, "master": False}, now=1060.0
    )
    assert ev2 is None
    assert PROJECT in gh.unpersisted_snapshots
    assert gh.last_observed_at == 1000.0

    # 3. Heartbeat at t=1060 also fails to dispatch and must NOT advance
    # lastObservedAt on ev1
    gh.heartbeat(now=1060.0)
    assert gh.last_observed_at == 1000.0
    persisted_ev1 = [e for e in store.other_events if e.get("id") == ev1][0]
    assert persisted_ev1["summary"]["lastObservedAt"] == 1000.0

    # 4. Simulate restart at t=1100: gap [1000, 1100] includes sc-1 at 1050
    gh_restarted = GateHistory(store, clock=clock)
    gap = gh_restarted.load(started_at=1100.0)
    assert gap is not None
    assert gap["unknown"] is True
    state = gh_restarted.toggles_at(PROJECT, 1070.0)
    assert state["state"] == "unknown_gap"

    # 5. If dispatch recovers on original instance, heartbeat flushes snapshot
    store.dispatch_event = orig_dispatch
    gh.heartbeat(now=1080.0)
    assert PROJECT not in gh.unpersisted_snapshots
    assert gh.last_observed_at == 1080.0


def test_attributes_preserves_source_event_changed_values_over_echo():
    """Changed keys use source-event values even if AYON entity echoed old."""
    writer = FakeKitsuWriter()
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "type": "Task",
        "name": "animation",
        "project_id": KITSU_PROJECT,
        "data": {"fps": 24.0, "frame_in": 1001, "frame_out": 1050},
        "nb_frames": 50,
    }

    resolver = MagicMock()
    # Simulate an inbound echo having overwritten AYON's attrib["fps"] back to
    # 24.0 while frameEnd (unchanged counterpart) is 1050 on the entity.
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": {"id": "kt-task-1"},
        "ayon": {
            "id": "task-1",
            "name": "animation",
            "taskType": "Animation",
            "attrib": {
                "fps": 24.0,
                "frameStart": 1001,
                "frameEnd": 1050,
            },
            "ownAttrib": {
                "fps": 24.0,
                "frameStart": 1001,
                "frameEnd": 1050,
            },
        },
    }

    ctx = MagicMock()
    ctx.event = {
        "topic": "entity.task.attrib_changed",
        "payload": {
            "newValue": {"fps": 30.0, "frameStart": 1010},
            "oldValue": {"fps": 24.0, "frameStart": 1001},
        },
    }
    ctx.entity_id = "task-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.conflict_policy = "kitsu_wins"
    ctx.processor = MagicMock()
    ctx.loop_guard_check.return_value = {"allowed": True}
    ctx.attempt = 1
    ctx.prior_writes = []

    res = handle_attributes(ctx)
    assert res.decision == DECISION_APPLIED
    assert len(writer.updated_fields) == 1
    written = writer.updated_fields[0]["fields"]
    assert written["data.fps"] == 30.0
    assert written["data.frame_in"] == 1010
    assert written["nb_frames"] == 41


def test_get_ayon_entity_task_explicitly_requests_own_attrib_fields():
    """IdentityResolver.get_ayon_entity passes fields with ownAttrib."""
    from processor.outbound.identity import IdentityResolver

    client = MagicMock()
    client.get_default_fields_for_type.return_value = {"id", "name", "data"}
    client.get_task_by_id.return_value = {"id": "t1", "name": "anim"}
    writer = FakeKitsuWriter()
    resolver = IdentityResolver(client, writer)

    ent = resolver.get_ayon_entity(PROJECT, "task", "t1")
    assert ent == {"id": "t1", "name": "anim"}
    client.get_task_by_id.assert_called_once()
    kwargs = client.get_task_by_id.call_args.kwargs
    assert kwargs.get("own_attributes") is True
    assert "ownAttrib" in kwargs.get("fields", set())
    assert "attrib" in kwargs.get("fields", set())


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


def test_unrelated_attribute_change_ignores_existing_invalid_frame_range():
    """Changing description/fps succeeds even if entity frame range invalid."""
    writer = FakeKitsuWriter()
    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
        "description": "old desc",
        "data": {"fps": 24.0},
    }

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": {"id": "kt-shot-1"},
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {
                "description": "New description",
                "frameStart": 100,
                "frameEnd": 90,
            },
            "ownAttrib": ["description"],
        },
    }

    ctx = MagicMock()
    ctx.event = {
        "topic": "entity.folder.attrib_changed",
        "payload": {
            "newValue": {"description": "New description"},
            "oldValue": {"description": "old desc"},
        },
    }
    ctx.entity_id = "fold-1"
    ctx.project_name = PROJECT
    ctx.kitsu_project_id = KITSU_PROJECT
    ctx.identity_resolver = resolver
    ctx.writer = writer
    ctx.conflict_policy = "kitsu_wins"
    ctx.processor = MagicMock()
    ctx.loop_guard_check.return_value = {"allowed": True}
    ctx.attempt = 1
    ctx.prior_writes = []

    res = handle_attributes(ctx)
    assert res.decision == DECISION_APPLIED
    assert writer.tasks["kt-shot-1"]["description"] == "New description"


def test_outbound_init_failure_blocks_startup_full_sync(monkeypatch):
    """Outbound init failure blocks full sync unless master known False."""
    from processor.processor import KitsuProcessor

    class StopLoop(Exception):
        pass

    clock = FakeClock(1000.0)
    store = FakeAyonStore(clock=clock)
    # Project A has outbound enabled (master=True); Project B has master=False
    store.project_settings["proj_enabled"] = {
        "sync_settings": {
            "two_way_sync": {"enabled": True, "task_status": True}
        }
    }
    store.project_settings["proj_disabled"] = {
        "sync_settings": {
            "two_way_sync": {"enabled": False, "task_status": False}
        }
    }

    proc = KitsuProcessor.__new__(KitsuProcessor)
    proc.pairing_list = {
        "kp-en": "proj_enabled",
        "kp-dis": "proj_disabled",
    }
    proc.ayon_api = store
    proc.addon_name = "kitsu"
    proc.addon_version = "0.0.0"
    proc.kitsu_server_url = "http://kitsu.local/api"
    proc.kitsu_login_email = "admin@example.com"
    proc.kitsu_login_password = "secret"
    proc.outbound = None

    def fail_writer(*args, **kwargs):
        raise RuntimeError("Kitsu unreachable during outbound init")

    monkeypatch.setattr(
        "processor.outbound.kitsu_writer.KitsuWriter.__init__",
        fail_writer,
    )

    full_sync_calls = []

    def fake_full_sync(processor, project_id, project_name):
        full_sync_calls.append((project_id, project_name))

    def fake_sleep(secs):
        raise StopLoop()

    monkeypatch.setattr(
        "processor.processor.project_full_sync", fake_full_sync
    )
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)

    with pytest.raises(StopLoop):
        proc.start_processing()

    # proj_enabled blocked because outbound is None / drain could not run;
    # proj_disabled allowed because settings watcher confirmed master=False.
    assert full_sync_calls == [("kp-dis", "proj_disabled")]


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


def test_task_assignees_preserves_assignments_for_unresolved_requested_users():
    """Unresolved requested users are not unassigned from Kitsu tasks."""
    from processor.outbound.handlers.task_assignees import (
        handle_task_assignees,
    )

    writer = FakeKitsuWriter()
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "type": "Task",
        "name": "anim",
        "project_id": KITSU_PROJECT,
        "assignees": ["p1", "p2"],
    }
    writer.persons = [
        {"id": "p1", "email": "alice@studio.com", "full_name": "Alice"},
        {"id": "p2", "email": "bob@studio.com", "full_name": "Bob"},
        {"id": "p3", "email": "bob@studio.com", "full_name": "Bob Dup"},
    ]

    # alice has a stale kitsu_id; bob has duplicate email in Kitsu.
    # Both fail forward resolution, while kitsu_person_owner maps p1->alice
    # and p2/p3->bob.
    ayon_users = [
        {"name": "alice", "kitsu_id": "stale-id", "email": "alice@studio.com"},
        {"name": "bob", "kitsu_id": None, "email": "bob@studio.com"},
    ]

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": writer.tasks["kt-task-1"],
        "ayon": {"id": "task-1", "name": "anim"},
    }
    from types import SimpleNamespace

    resolver.ayon_client = SimpleNamespace(users=ayon_users)

    ctx = SimpleNamespace(
        event={
            "topic": "entity.task.assignees_changed",
            "user": "artist",
            "payload": {"newValue": ["alice", "bob"]},
        },
        entity_id="task-1",
        project_name=PROJECT,
        kitsu_project_id=KITSU_PROJECT,
        identity_resolver=resolver,
        writer=writer,
        conflict_policy="ayon_wins",
        processor=MagicMock(),
        loop_guard_check=lambda *args: {"allowed": True},
        attempt=1,
        prior_writes=[],
        prior_not_written=None,
    )

    res = handle_task_assignees(ctx)
    assert res.decision == DECISION_APPLIED
    assert writer.unassigned == []
    assert writer.tasks["kt-task-1"]["assignees"] == ["p1", "p2"]


def test_attributes_discards_guard_reservations_for_suppressed_frame_fields():
    """Suppressed frame fields do not commit pending guard reservations."""
    clock = FakeClock(100.0)
    store = FakeAyonStore(clock=clock)
    writer = FakeKitsuWriter()
    processor = MagicMock()
    processor.sender = "proc-1"
    processor.pairing_list = {PROJECT: KITSU_PROJECT}

    runner = OutboundJobRunner(
        processor=processor,
        clock=clock,
        ayon_client=store,
        writer=writer,
        sender="proc-1",
    )
    runner.loop_guard_state = {
        ("fold-1", "data.frame_in"): {
            "write_times": [90.0, 91.0, 92.0],
            "suppressed_until": 392.0,
        },
        ("fold-1", "data.frame_out"): {
            "write_times": [90.0, 91.0],
            "suppressed_until": None,
        },
    }

    writer.tasks["kt-shot-1"] = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
        "data": {"frame_in": 1, "frame_out": 10, "fps": 24.0},
        "nb_frames": 10,
    }

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": writer.tasks["kt-shot-1"],
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {"frameStart": 2, "frameEnd": 20, "fps": 25.0},
            "ownAttrib": ["frameStart", "frameEnd", "fps"],
        },
    }

    from types import SimpleNamespace

    ctx = SimpleNamespace(
        event={
            "topic": "entity.folder.attrib_changed",
            "payload": {
                "newValue": {"frameStart": 2, "frameEnd": 20, "fps": 25.0}
            },
        },
        prior_writes=[],
        entity_id="fold-1",
        project_name=PROJECT,
        kitsu_project_id=KITSU_PROJECT,
        identity_resolver=resolver,
        writer=writer,
        conflict_policy="ayon_wins",
        loop_guard_check=runner.loop_guard_check,
        loop_guard_commit=runner.loop_guard_commit,
        loop_guard_discard=runner.loop_guard_discard,
        omitted_fields=[],
        processor=None,
        attempt=1,
    )

    res = handle_attributes(ctx)
    assert res.decision == DECISION_APPLIED
    assert len(writer.updated_fields) == 1
    assert writer.updated_fields[0]["fields"] == {"data.fps": 25.0}
    # data.frame_out must NOT have recorded a 3rd write or opened suppression
    frame_out_guard = runner.loop_guard_state.get(("fold-1", "data.frame_out"))
    assert frame_out_guard == {
        "write_times": [90.0, 91.0],
        "suppressed_until": None,
    }
    fps_guard = runner.loop_guard_state.get(("fold-1", "data.fps"))
    assert fps_guard == {
        "write_times": [100.0],
        "suppressed_until": None,
    }


def test_transient_gate_history_load_failure_recovers_before_enrolling(
    monkeypatch,
):
    """Startup gate_history.load failure recovers before enrolling jobs."""
    from processor.processor import KitsuProcessor

    class StopLoop(Exception):
        pass

    clock = FakeClock(1000.0)
    store = FakeAyonStore(clock=clock)
    writer = FakeKitsuWriter()
    writer.tasks["kt-1"] = {
        "id": "kt-1",
        "type": "Task",
        "name": "anim",
        "project_id": KITSU_PROJECT,
        "task_status_id": "st-todo",
    }
    writer.statuses = [
        {"id": "st-todo", "name": "Todo", "short_name": "todo"},
        {"id": "st-done", "name": "Done", "short_name": "done"},
    ]
    store.entities[("task", "t1")] = {
        "id": "t1",
        "name": "anim",
        "status": "Done",
        "data": {"kitsuId": "kt-1"},
    }

    # Persisted gate snapshot at t=500 enabling task_status
    store.other_events.append(
        {
            "id": "gate-1",
            "topic": "kitsu.outbound_gate",
            "project": PROJECT,
            "createdAt": 500.0,
            "summary": {
                "project": PROJECT,
                "toggles": {
                    "valid": True,
                    "master": True,
                    "categories": {
                        "task_status": True,
                        "task_assignees": False,
                        "entity_attributes": False,
                        "entity_creation": False,
                        "entity_rename": False,
                        "entity_deletion": False,
                    },
                    "conflict_policy": "kitsu_wins",
                },
                "observedAt": 500.0,
                "lastObservedAt": 995.0,
            },
        }
    )

    # Source event created at t=800 (before startup at t=1000)
    store.add_source_event(
        event_id="src-old-1",
        topic="entity.task.status_changed",
        project_name=PROJECT,
        created_at=800.0,
        summary={"entityId": "t1"},
        user="artist",
        payload={"oldValue": "Todo", "newValue": "Done"},
    )

    proc = KitsuProcessor.__new__(KitsuProcessor)
    proc.clock = clock
    proc.ayon_api = store
    proc.entrypoint = "/addons/kitsu/1.2.4"
    proc.pairing_list = {KITSU_PROJECT: PROJECT}
    proc.outbound = None

    from processor.outbound.identity import IdentityResolver
    from processor.outbound.runner import OutboundJobRunner
    from processor.outbound.settings_watch import GateHistory, SettingsWatcher

    gate_history = GateHistory(store, clock=clock)
    gate_history.loaded = False
    watcher = SettingsWatcher(
        store,
        pairing_list_getter=proc.get_outbound_pairings,
        gate_history=gate_history,
        clock=clock,
    )
    identity = IdentityResolver(store, writer, entrypoint=proc.entrypoint)
    proc.outbound = OutboundJobRunner(
        processor=proc,
        clock=clock,
        ayon_client=store,
        writer=writer,
        settings_watcher=watcher,
        gate_history=gate_history,
        identity_resolver=identity,
        sender="proc-test",
    )

    orig_load = gate_history.load
    load_attempts = [0]

    def flaky_load(*args, **kwargs):
        load_attempts[0] += 1
        if load_attempts[0] == 1:
            gate_history.loaded = False
            raise RuntimeError("Transient AYON event query failure")
        return orig_load(*args, **kwargs)

    monkeypatch.setattr(gate_history, "load", flaky_load)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *a, **k: None
    )
    monkeypatch.setattr(proc, "_poll_sync_request_once", lambda: False)
    monkeypatch.setattr("time.time", clock)

    def stop_on_sleep(secs):
        raise StopLoop()

    monkeypatch.setattr("time.sleep", stop_on_sleep)

    with pytest.raises(StopLoop):
        proc.start_processing()

    # Load failed on startup (attempt 1) and recovered in main loop (attempt 2)
    assert load_attempts[0] >= 2
    assert gate_history.loaded is True
    # Job created at t=800 was applied rather than skipped as no_history
    assert len(store.jobs) == 1
    job = list(store.jobs.values())[0]
    assert job["status"] == "finished"
    assert job["summary"]["decision"] == DECISION_APPLIED








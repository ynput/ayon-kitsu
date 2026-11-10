"""Tests for in-flight creation coordination.

Inbound Kitsu events that race an outbound creation must wait for
it, and are deferred and replayed when the wait times out.
"""

import pytest

from .offline import block_network  # noqa: F401
from .outbound_fakes import FakeKitsuWriter
from .outbound_harness import KITSU_PROJECT, PROJECT
from processor.outbound.constants import TOPIC_FOLDER_CREATED
from processor.outbound.handlers.creation import handle_creation
from processor.processor import KitsuProcessor
from unittest.mock import MagicMock, patch
import processor.update_from_kitsu as update_from_kitsu
import threading

pytestmark = pytest.mark.usefixtures("block_network")


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
        return {"id": "kt-new", "data": kw["data"]}

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
    ctx.category = "entity_creation"
    ctx.job_id = "creation-job"
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

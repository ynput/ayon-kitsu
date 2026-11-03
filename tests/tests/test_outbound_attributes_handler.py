"""Handler-level tests for outbound attribute sync.

Covers inherited fields, conflicts, loop-guard reservations,
partial writes after supersession and empty descriptions.
"""

import pytest

from .offline import block_network  # noqa: F401
from .outbound_fakes import FakeAyonStore, FakeClock, FakeKitsuWriter
from .outbound_harness import KITSU_PROJECT, PROJECT
from processor.outbound.constants import DECISION_APPLIED, DECISION_SKIPPED
from processor.outbound.handlers.attributes import handle_attributes
from processor.outbound.runner import OutboundJobRunner
from unittest.mock import MagicMock

pytestmark = pytest.mark.usefixtures("block_network")


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
    ctx.category = "entity_attributes"
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
    ctx.category = "entity_attributes"
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
    ctx.category = "entity_attributes"
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
    ctx.category = "entity_attributes"
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
    ctx.category = "entity_attributes"
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
    ctx.category = "entity_attributes"
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


def test_attributes_discards_guard_reservations_for_suppressed_frame_fields():
    """Suppressed frame fields do not commit pending guard reservations."""
    clock = FakeClock(100.0)
    store = FakeAyonStore(clock=clock)
    writer = FakeKitsuWriter()
    processor = MagicMock()
    processor.sender = "proc-1"
    processor.get_outbound_pairings.return_value = {PROJECT: KITSU_PROJECT}

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
        category="entity_attributes",
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


def test_retry_omits_fields_superseded_by_newer_job():
    """A newer applied job's fields are omitted from the retry."""
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
    ctx.category = "entity_attributes"
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


def test_kitsu_attrib_view_preserves_empty_description():
    """kitsu_attrib_view preserves empty string descriptions."""
    from processor.outbound.mapping import kitsu_attrib_view

    view1 = kitsu_attrib_view({"description": "", "data": {}})
    assert view1.get("description") == ""

    view2 = kitsu_attrib_view({"description": None, "data": {}})
    assert view2.get("description") == ""

    view3 = kitsu_attrib_view({"data": {}})
    assert "description" not in view3


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

def test_attributes_frame_end_edit_derives_kitsu_end_via_fallback_start():
    """Frame-range comparison uses fallback start to derive Kitsu end frame.

    When Kitsu has nb_frames but no data.frame_in/frame_out, inbound sync
    derives end frame using the AYON fallback start. Outbound conflict check
    must supply the pre-change fallback start so an ordinary end-frame edit
    is not falsely rejected as a conflict under kitsu_wins.
    """
    writer = FakeKitsuWriter()
    kitsu_shot = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
        "nb_frames": 100,
        "data": {},
    }
    writer.tasks["kt-shot-1"] = kitsu_shot

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": kitsu_shot,
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {"frameStart": 1001, "frameEnd": 1101},
            "own_attributes": ["frameStart", "frameEnd"],
        },
    }

    ctx = MagicMock()
    ctx.category = "entity_attributes"
    ctx.event = {
        "topic": "entity.folder.attrib_changed",
        "payload": {
            "changed": {"frameEnd": 1101},
            "oldValue": {"frameEnd": 1100},
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
    ctx.omitted_fields = []

    res = handle_attributes(ctx)
    assert res.decision == DECISION_APPLIED
    assert len(writer.updated_fields) == 1
    updated = writer.updated_fields[0]["fields"]
    assert updated.get("data.frame_out") == 1101
    assert updated.get("nb_frames") == 101

def test_retry_omits_frame_range_fields_atomically():
    """Superseding any frame field atomically omits all frame-range fields.

    When nb_frames was superseded by a newer applied job, retrying an older
    frame-start edit must not send partial data.frame_in to Kitsu without
    nb_frames, which would corrupt the derived end frame.
    """
    writer = FakeKitsuWriter()
    kitsu_shot = {
        "id": "kt-shot-1",
        "type": "Shot",
        "name": "sh010",
        "project_id": KITSU_PROJECT,
        "nb_frames": 200,
        "data": {"frame_in": 1001, "frame_out": 1200},
    }
    writer.tasks["kt-shot-1"] = kitsu_shot

    resolver = MagicMock()
    resolver.resolve.return_value = {
        "ok": True,
        "kitsu": kitsu_shot,
        "ayon": {
            "id": "fold-1",
            "name": "sh010",
            "folderType": "Shot",
            "attrib": {"frameStart": 1010, "frameEnd": 1200},
            "own_attributes": ["frameStart", "frameEnd"],
        },
    }

    ctx = MagicMock()
    ctx.category = "entity_attributes"
    ctx.event = {
        "topic": "entity.folder.attrib_changed",
        "payload": {
            "changed": {"frameStart": 1010},
            "oldValue": {"frameStart": 1001},
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
    # nb_frames was superseded by newer applied frame-end job
    ctx.omitted_fields = ["nb_frames"]

    res = handle_attributes(ctx)
    assert res.decision == DECISION_SKIPPED
    assert len(writer.updated_fields) == 0


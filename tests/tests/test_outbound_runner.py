"""Unit tests for OutboundJobRunner lifecycle and dispatch (Task 10.4).

Validates: Requirements 4.1, 4.2, 4.10, 4.11, 6.1, 9.4, 10.1, 10.4,
10.5, 10.9.
"""

from unittest.mock import MagicMock, patch
import pytest

from processor.outbound.constants import (
    FINAL_RETRIES_VALUE,
    TARGET_TOPIC,
)
from processor.outbound.kitsu_writer import KitsuWriterError
from processor.outbound.runner import OutboundJobRunner

from .offline import block_network  # noqa: F401
from .outbound_harness import build_runner
from .outbound_fakes import FakeAyonStore, FakeClock, FakeKitsuWriter
from .outbound_harness import KITSU_PROJECT, PROJECT, setup_runner
from processor.outbound.settings_watch import GateHistory

pytestmark = pytest.mark.usefixtures("block_network")


def _setup_runner(clock=None, store=None, writer=None):
    h = build_runner(clock=clock, store=store, writer=writer)
    return h.clock, h.store, h.writer, h.runner, h.processor


@pytest.mark.parametrize("refresh_before_poll", [False, True])
def test_job_skips_unobserved_toggle_changes(refresh_before_poll):
    """A disable and re-enable between polls leaves a durable gate gap."""
    h = build_runner()
    for index, moment in enumerate((1005.0, 1015.0)):
        h.store.other_events.append(
            {
                "id": f"setting-{index}",
                "topic": "settings.changed",
                "createdAt": moment,
                "project": PROJECT,
                "summary": {"addon_name": "kitsu"},
            }
        )
    h.store.add_source_event(
        event_id="evt-between-toggles",
        topic="entity.task.status_changed",
        project_name=PROJECT,
        created_at=1010.0,
        summary={"taskId": "task"},
    )
    h.clock.advance(20)
    if refresh_before_poll:
        h.watcher.refresh()

    assert h.runner.poll_once()
    assert h.store.jobs["job-1"]["summary"]["decision"] == "skipped"
    assert "toggle state was unknown" in h.store.jobs["job-1"]["description"]
    assert h.writer.comments == []

    history = GateHistory(h.store, clock=h.clock)
    history.load()
    assert history.toggles_at(PROJECT, 1010.0)["state"] == "unknown_gap"
    assert history.toggles_at(PROJECT, 1004.0)["state"] == "snapshot"
    assert history.toggles_at("unrelated", 1010.0)["state"] == "no_history"


def test_in_progress_before_kitsu_calls():
    """Job is set in_progress before any Kitsu write request (Req 4.2)."""
    clock, store, writer, runner, _ = _setup_runner()

    # Setup entity and task in store and writer
    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "name": "modeling",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }

    # Add change event
    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    ran = runner.poll_once()
    assert ran is True

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Applied:" in job["description"]
    assert len(writer.comments) == 1
    assert writer.comments[0]["status"]["name"] == "Done"


def test_ayon_down_at_in_progress():
    """No Kitsu write is sent when in_progress update fails (Req 4.11)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    store.fail_in_progress = True
    ran = runner.poll_once()

    assert ran is False
    # Zero Kitsu writes sent
    assert len(writer.comments) == 0


def test_ayon_down_at_final_update_retried():
    """Failed final update is retried alone with no Kitsu resend (Req 4.11)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    store.fail_final_update = True
    runner.poll_once()

    # Kitsu comment was sent
    assert len(writer.comments) == 1
    assert runner.pending_ayon_update is not None

    # Next poll retries update alone; zero additional Kitsu calls
    clock.advance(2.0)
    runner.poll_once()

    assert runner.pending_ayon_update is None
    assert len(writer.comments) == 1
    assert store.jobs["job-1"]["status"] == "finished"


def test_entity_gone_skips():
    """Missing AYON entity skips with entity no longer exists (Req 4.10)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-gone"},
    )

    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "finished"
    assert "Skipped:" in job["description"]
    assert "no longer exists" in job["description"]
    assert len(writer.comments) == 0


def test_retryable_failure_and_retry_hold():
    """Retryable failure holds job and retries on attempt 2 (Req 10.1)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    writer.error_on_comment = KitsuWriterError("unreachable", None, "timeout")

    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    # First attempt fails with unreachable
    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "pending"
    assert job["summary"]["attempt"] == 1
    assert runner.held_job is not None

    # While held (< 10s), polling does not retry
    clock.advance(5.0)
    ran = runner.poll_once()
    assert ran is False

    # After 10s, retry runs
    writer.error_on_comment = None
    clock.advance(6.0)
    ran2 = runner.poll_once()
    assert ran2 is True

    assert job["status"] == "finished"
    assert job["summary"]["attempt"] == 2
    assert len(writer.comments) == 1


def test_retryable_failure_final_on_fourth_attempt():
    """Fourth retryable failure is final with unwritten values (Req 10.6)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    writer.error_on_comment = KitsuWriterError("unreachable", None, "timeout")

    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    # Attempts 1, 2, 3 fail
    for _ in range(3):
        runner.poll_once()
        clock.advance(15.0)

    # Attempt 4 fails finally
    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert job["retries"] == FINAL_RETRIES_VALUE
    assert "Failed:" in job["description"]
    assert "unwritten values:" in job["description"]


def test_unexpected_exception_logged_and_final():
    """Unexpected exception in handler marks job failed finally (Req 10.4)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    # Cause unexpected KeyError in task_statuses
    writer.task_statuses = MagicMock(side_effect=KeyError("unexpected"))

    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    runner.poll_once()

    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert job["retries"] == FINAL_RETRIES_VALUE
    assert "KeyError" in job["description"]


def test_interrupted_job_at_start():
    """Own in_progress job found at start is interrupted (Req 10.9)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.jobs["job-old"] = {
        "id": "job-old",
        "topic": TARGET_TOPIC,
        "sender": runner.sender,
        "status": "in_progress",
        "summary": {"attempt": 1, "entityId": "task-1", "kitsuId": "kt-1"},
        "project_name": "test-project",
    }

    runner.recover_interrupted()

    job = store.jobs["job-old"]
    assert job["status"] == "pending"
    assert (
        "Interrupted by a Processor stop (attempt 1/4)"
        in job["description"]
    )
    assert runner.held_job is not None


def test_stale_job_reaped():
    """Stale in_progress job of other sender >300s is reaped (Req 4.9)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.jobs["job-other"] = {
        "id": "job-other",
        "topic": TARGET_TOPIC,
        "sender": "kitsu-processor-other-host",
        "status": "in_progress",
        "summary": {"attempt": 1},
        "updatedAt": 500.0,
        "project_name": "test-project",
    }

    clock.advance(1000.0)  # idle for > 300s
    runner.reap_stale()

    job = store.jobs["job-other"]
    assert job["status"] == "failed"
    assert "Abandoned by kitsu-processor-other-host" in job["description"]


def test_recovery_and_reaping_follow_runner_topic():
    """An isolated runner must leave stale and interrupted real jobs alone."""
    clock, store, _, runner, _ = _setup_runner()
    runner.TARGET_TOPIC = "kitsu.live_validation.isolated"
    for prefix, topic in (
        ("real", TARGET_TOPIC),
        ("test", runner.TARGET_TOPIC),
    ):
        for suffix, sender in (
            ("own", runner.sender),
            ("foreign", "other-processor"),
        ):
            job_id = f"{prefix}-{suffix}"
            store.jobs[job_id] = {
                "id": job_id,
                "topic": topic,
                "sender": sender,
                "status": "in_progress",
                "summary": {"attempt": 1},
                "updatedAt": clock() - 600,
                "project_name": PROJECT,
            }

    runner.recover_interrupted()
    runner.reap_stale()

    assert store.jobs["real-own"]["status"] == "in_progress"
    assert store.jobs["real-foreign"]["status"] == "in_progress"
    assert store.jobs["real-foreign"]["sender"] == "other-processor"
    assert store.jobs["test-own"]["status"] == "pending"
    assert runner.held_job["job"]["id"] == "test-own"
    assert store.jobs["test-foreign"]["status"] == "failed"


@pytest.mark.parametrize("pull_fails", [False, True])
def test_kitsu_wins_inbound_pull(pull_fails):
    """Conflict with kitsu_wins policy triggers inbound task pull (Req 9.4)."""
    clock, store, writer, runner, processor = _setup_runner()
    if pull_fails:
        processor.pull_kitsu_task.side_effect = RuntimeError("AYON unavailable")

    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    # Current Kitsu status is "Approved", differing from prev and new
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-app",
    }

    store.add_source_event(
        event_id="evt-1",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    runner.poll_once()

    job = store.jobs["job-1"]
    processor.pull_kitsu_task.assert_called_once_with(
        "kt-task-1", {**writer.tasks["kt-task-1"], "type": "Task"}
    )
    if pull_fails:
        assert job["status"] == "pending"
        assert "Inbound pull on conflict failed" in job["description"]
        assert "AYON unavailable" in job["description"]
    else:
        assert job["status"] == "finished"
        assert "Conflict:" in job["description"]
    assert "no kitsu field was written" in job["description"].lower()
    # Zero Kitsu writes sent
    assert len(writer.comments) == 0


def test_terminal_failure_keeps_description_delimiters_in_error_text():
    """Error text containing description clauses survives final formatting."""
    _, store, writer, runner, _ = _setup_runner()
    message = (
        "Invalid value. Written fields: artist note, additional detail. "
        "No Kitsu field was written. Keep this trailing explanation."
    )
    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": KITSU_PROJECT,
        "task_status_id": "st-wip",
    }
    writer.comment_status = MagicMock(
        side_effect=KitsuWriterError(
            "rejected", message, http_status=422, retryable=False
        )
    )
    store.add_source_event(
        event_id="src-delimiters",
        topic="entity.task.status_changed",
        project_name=PROJECT,
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    runner._process_job(runner._enroll(), attempt=4)

    job = store.jobs["job-1"]
    assert job["status"] == "failed"
    assert message in job["description"]
    assert job["description"].count("attempt 4/4") == 1
    assert job["summary"]["notWritten"] == {"task_status_id": "Done"}


def test_legacy_unwritten_records_survive_source_lookup_failure():
    """A restarted job can report unwritten values saved as legacy records."""
    _, store, _, runner, _ = _setup_runner()
    store.jobs["legacy-job"] = {
        "id": "legacy-job",
        "dependsOn": "missing-source",
        "project_name": PROJECT,
        "summary": {
            "attempt": 4,
            "writes": [{"field": "data.fps", "before": 24, "sent": 25}],
            "notWritten": [
                {"field": "description", "ayonValue": "Artist's edit"},
                {"field": "data.frame_out", "ayonValue": 120},
            ],
        },
    }

    runner._process_job(store.jobs["legacy-job"], attempt=4)

    job = store.jobs["legacy-job"]
    assert job["status"] == "failed"
    assert job["summary"]["notWritten"] == {
        "description": "Artist's edit", "data.frame_out": 120,
    }
    assert "Source event missing-source not found" in job["description"]
    assert "description=Artist's edit" in job["description"]
    assert "data.frame_out=120" in job["description"]
    assert "field 'data.fps'" in job["description"]


def test_drain_order_and_failed_job_list():
    """Drain processes jobs in ascending creation time order (Req 10.5)."""
    clock, store, writer, runner, _ = _setup_runner()

    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    store.entities[("task", "task-2")] = {
        "id": "task-2",
        "data": {"kitsuId": "kt-task-2"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    writer.tasks["kt-task-2"] = {
        "id": "kt-task-2",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }

    # Event 2 created earlier than Event 1
    store.add_source_event(
        event_id="evt-older",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1005.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-2"},
    )
    store.add_source_event(
        event_id="evt-newer",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1010.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )

    failed = runner.drain()
    assert len(failed) == 0
    # First comment was for task-2 (older event)
    assert writer.comments[0]["task"]["id"] == "kt-task-2"
    assert writer.comments[1]["task"]["id"] == "kt-task-1"


def test_drain_raises_on_enroll_failure():
    """Drain raises RuntimeError when enroll fails (Req 10.5)."""
    clock, store, writer, runner, _ = _setup_runner()
    store.enroll_event_job = MagicMock(
        side_effect=RuntimeError("enroll connection refused")
    )
    with pytest.raises(RuntimeError, match="Enroll failed during drain"):
        runner.drain()


def test_drain_raises_on_get_events_failure():
    """Drain raises RuntimeError when pending query fails (Req 10.5)."""
    clock, store, writer, runner, _ = _setup_runner()
    store.get_events = MagicMock(
        side_effect=RuntimeError("query failed")
    )
    with pytest.raises(
        RuntimeError, match="Failed querying pending jobs during drain"
    ):
        runner.drain()


def test_recover_interrupted_picks_up_pending_job():
    """Own pending job at start is recovered into held_job (Req 10.9)."""
    clock, store, writer, runner, _ = _setup_runner()
    job_id = "job-pending-1"
    store.jobs[job_id] = {
        "id": job_id,
        "topic": TARGET_TOPIC,
        "sender": runner.sender,
        "status": "pending",
        "project_name": "test-project",
        "summary": {
            "entityId": "task-1",
            "kitsuId": "kt-1",
            "attempt": 1,
            "lastFailedAt": 950.0,
        },
    }
    runner.recover_interrupted()
    assert runner.held_job is not None
    assert runner.held_job["job"]["id"] == job_id
    assert runner.held_job["attempt"] == 2
    assert runner.held_job["last_failed_at"] == 950.0


def test_reap_stale_reaps_pending_job():
    """Foreign pending job idle > 300s is reaped as failed (Req 4.9)."""
    clock, store, writer, runner, _ = _setup_runner()
    job_id = "job-foreign-pending"
    store.jobs[job_id] = {
        "id": job_id,
        "topic": TARGET_TOPIC,
        "sender": "kitsu-processor-foreign",
        "status": "pending",
        "project_name": "test-project",
        "updatedAt": 600.0,
        "summary": {
            "entityId": "task-1",
            "attempt": 1,
            "lastFailedAt": 600.0,
        },
    }
    clock.current_time = 1000.0  # 400s idle
    runner.reap_stale()
    updated = store.jobs[job_id]
    assert updated["status"] == "failed"
    assert "Abandoned by kitsu-processor-foreign" in updated["description"]


def test_supersession_filters_by_category_and_source_time():
    """Supersession only matches same category and newer source event."""
    clock, store, writer, runner, _ = _setup_runner()
    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    # Retried event at t=1002.0
    store.add_source_event(
        event_id="evt-retried",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1002.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )
    # Candidate 1: different category at t=1010.0 -> no supersession
    store.jobs["cand-diff-cat"] = {
        "id": "cand-diff-cat",
        "topic": TARGET_TOPIC,
        "status": "finished",
        "project_name": "test-project",
        "summary": {
            "entityId": "task-1",
            "category": "entity_attributes",
            "sourceCreatedAt": 1010.0,
            "writes": [{"field": "task_status_id"}],
        },
    }
    # Candidate 2: same category but older source event t=1001.0 -> no
    store.jobs["cand-older-src"] = {
        "id": "cand-older-src",
        "topic": TARGET_TOPIC,
        "status": "finished",
        "project_name": "test-project",
        "summary": {
            "entityId": "task-1",
            "category": "task_status",
            "sourceCreatedAt": 1001.0,
            "writes": [{"field": "task_status_id"}],
        },
    }

    # Attempt 2 with no valid candidate supersession -> applies write
    ran = runner.poll_once()
    assert ran is True
    # Now candidate 3: same category AND newer source event t=1020.0
    store.jobs["cand-newer-src"] = {
        "id": "cand-newer-src",
        "topic": TARGET_TOPIC,
        "status": "finished",
        "project_name": "test-project",
        "summary": {
            "entityId": "task-1",
            "category": "task_status",
            "sourceCreatedAt": 1020.0,
            "writes": [{"field": "task_status_id"}],
        },
    }
    # Simulate a second retried job for task-1
    store.add_source_event(
        event_id="evt-retried-2",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1005.0,
        payload={"oldValue": "WIP", "newValue": "Approved"},
        summary={"entityId": "task-1"},
    )
    # Put job in store with attempt=2
    job2_id = "job-retried-2"
    store.jobs[job2_id] = {
        "id": job2_id,
        "topic": TARGET_TOPIC,
        "dependsOn": "evt-retried-2",
        "sender": runner.sender,
        "status": "pending",
        "project_name": "test-project",
        "summary": {
            "entityId": "task-1",
            "attempt": 1,
            "lastFailedAt": 1010.0,
        },
    }
    clock.current_time = 1015.0
    # Recover and run attempt 2
    runner.recover_interrupted()
    clock.advance(15.0)
    ran2 = runner.poll_once()
    assert ran2 is True
    fin = store.jobs[job2_id]
    assert fin["status"] == "finished"
    assert "Skipped:" in fin["description"]
    assert "cand-newer-src" in fin["summary"]["omittedBy"]


@pytest.mark.parametrize(
    "cand_time,should_supersede",
    [
        (None, False),
        ("invalid-time", False),
        (1004.0, False),
        (1005.0, False),
        (1006.0, True),
    ],
)
def test_supersession_retry_source_time_validation(
    cand_time, should_supersede
):
    """Retry supersession requires strictly newer source time (10.7)."""
    clock, store, writer, runner, _ = _setup_runner()
    store.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kt-task-1"},
    }
    writer.tasks["kt-task-1"] = {
        "id": "kt-task-1",
        "project_id": "kitsu-proj-1",
        "task_status_id": "st-wip",
    }
    store.add_source_event(
        event_id="evt-retry",
        topic="entity.task.status_changed",
        project_name="test-project",
        created_at=1005.0,
        payload={"oldValue": "WIP", "newValue": "Done"},
        summary={"entityId": "task-1"},
    )
    cand_summary = {
        "entityId": "task-1",
        "category": "task_status",
        "writes": [{"field": "task_status_id"}],
    }
    if cand_time is not None:
        cand_summary["sourceCreatedAt"] = cand_time

    store.jobs["cand-job"] = {
        "id": "cand-job",
        "topic": TARGET_TOPIC,
        "status": "finished",
        "project_name": "test-project",
        "summary": cand_summary,
    }
    job_id = "job-retry"
    store.jobs[job_id] = {
        "id": job_id,
        "topic": TARGET_TOPIC,
        "dependsOn": "evt-retry",
        "sender": runner.sender,
        "status": "pending",
        "project_name": "test-project",
        "summary": {
            "entityId": "task-1",
            "attempt": 1,
            "lastFailedAt": 1010.0,
        },
    }
    clock.current_time = 1015.0
    runner.recover_interrupted()
    clock.advance(15.0)
    ran = runner.poll_once()
    assert ran is True
    fin = store.jobs[job_id]
    assert fin["status"] == "finished"
    if should_supersede:
        assert "Skipped:" in fin["description"]
        assert "cand-job" in fin["summary"]["omittedBy"]
    else:
        assert "Applied:" in fin["description"]
        assert not fin.get("summary", {}).get("omittedBy")


def test_kitsu_writer_init_redacts_secrets_in_logs(caplog):
    """Writer init error logs redact secrets (Req 13.6)."""
    import logging
    clock, store, _, _, _ = _setup_runner()
    secret = "SuperSecretKitsuPass999!"
    proc = MagicMock()
    proc.sender = "kitsu-processor-test"
    proc.kitsu_host = "https://kitsu.example.com"
    proc.kitsu_login_password = secret
    proc.get_outbound_pairings.return_value = {"test-project": "kitsu-proj-1"}

    with caplog.at_level(logging.WARNING):
        with patch(
            "processor.outbound.runner.KitsuWriter",
            side_effect=RuntimeError(
                f"Connection failed: password={secret}"
            ),
        ):
            runner = OutboundJobRunner(
                processor=proc,
                clock=clock,
                ayon_client=store,
                writer=None,
                sender="kitsu-processor-test",
            )
            assert runner.writer is None

    assert secret not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_drain_exceptions_redact_secrets_and_suppress_cause():
    """Drain exceptions redact secrets and suppress cause (10.5, 13.6)."""
    clock, store, _, runner, processor = _setup_runner()
    secret = "TopSecretDrainToken456!"
    processor.kitsu_login_password = secret

    # Case 1: enroll_event_job fails during drain with secret
    with patch.object(
        store,
        "enroll_event_job",
        side_effect=RuntimeError(f"Enroll failed: {secret}"),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            runner.drain()
        msg = str(exc_info.value)
        assert secret not in msg
        assert exc_info.value.__cause__ is None

    # Case 2: get_events query failure contains secret
    runner.last_enroll_error = None
    with patch.object(
        store,
        "get_events",
        side_effect=RuntimeError(f"AYON query failed: {secret}"),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            runner.drain()
        msg = str(exc_info.value)
        assert secret not in msg
        assert exc_info.value.__cause__ is None


def test_poll_inbound_sync_request_deferred_during_drain():
    """Requirement: defer inbound full syncs until drain completes."""
    _, _, _, runner, processor = setup_runner()
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
    _, store, _, runner, _ = setup_runner()

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
    _, _, _, runner, _ = setup_runner()

    with patch.object(
        runner, "reap_stale", side_effect=RuntimeError("Simulated error")
    ):
        with pytest.raises(RuntimeError):
            runner.drain()

    assert runner.in_drain is False


def test_runner_holds_job_on_transient_source_event_fetch_error():
    """Transient source-event fetch errors are retryable, id preserved."""
    _, store, _, runner, _ = setup_runner()

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
    desc = stored_job["description"]
    assert "Transient error fetching source event" in desc

    # The held job keeps the source event id for the retry.
    assert runner.held_job is not None
    assert runner.held_job["job"]["dependsOn"] == "evt-source"
    assert runner.held_job["job"]["summary"]["sourceEventId"] == (
        "evt-source"
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
    _, _, _, runner, _ = setup_runner(enabled=True)
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


def test_retried_fields_for_job_by_category():
    """Supersession derives the written fields from the category."""
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


def test_drain_aborts_on_enroll_server_error():
    """Server errors (HTTP >= 500) during enroll must abort drain."""
    clock, store, writer, runner, _ = setup_runner(enabled=True)
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
    clock, store, writer, runner, _ = setup_runner(enabled=True)
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
    clock, store, writer, runner, _ = setup_runner(enabled=True)

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
    clock, store, writer, runner, _ = setup_runner(enabled=True)
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
    clock, store, writer, runner, _ = setup_runner(enabled=True)
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

    clock, store, writer, runner, _ = setup_runner(enabled=True)
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


def test_reaped_abandoned_job_transfers_ownership_and_unblocks_enroll():
    """Reaped foreign abandoned job transfers sender and unblocks enrollment.
    """
    clock = FakeClock(1000.0)
    store = FakeAyonStore(clock=clock)
    writer = FakeKitsuWriter()
    processor = MagicMock()
    processor.sender = "processor-B"
    processor.get_outbound_pairings.return_value = {PROJECT: KITSU_PROJECT}

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
    clock, store, writer, runner, _ = setup_runner(enabled=True)
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

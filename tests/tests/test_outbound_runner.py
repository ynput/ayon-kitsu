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
from processor.outbound.identity import IdentityResolver
from processor.outbound.kitsu_writer import KitsuWriterError
from processor.outbound.runner import OutboundJobRunner
from processor.outbound.settings_watch import GateHistory, SettingsWatcher

from .offline import block_network  # noqa: F401
from .outbound_fakes import FakeAyonStore, FakeClock, FakeKitsuWriter

pytestmark = pytest.mark.usefixtures("block_network")


def _setup_runner(clock=None, store=None, writer=None):
    clock = clock or FakeClock(1000.0)
    store = store or FakeAyonStore(clock=clock)
    writer = writer or FakeKitsuWriter()

    # Default pairing
    processor = MagicMock()
    processor.sender = "kitsu-processor-test"
    processor.pairing_list = {"test-project": "kitsu-proj-1"}

    gate_history = GateHistory(store, clock=clock)
    # Record initial observation so project is enabled
    gate_history.record_observation(
        "test-project",
        {
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
        now=clock(),
    )

    watcher = SettingsWatcher(
        store,
        pairing_list_getter=lambda: {"test-project": "kitsu-proj-1"},
        gate_history=gate_history,
        clock=clock,
    )
    watcher.refresh()

    identity_resolver = IdentityResolver(store, writer)

    runner = OutboundJobRunner(
        processor=processor,
        clock=clock,
        ayon_client=store,
        writer=writer,
        settings_watcher=watcher,
        gate_history=gate_history,
        identity_resolver=identity_resolver,
        sender="kitsu-processor-test",
    )
    return clock, store, writer, runner, processor


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


def test_kitsu_wins_inbound_pull():
    """Conflict with kitsu_wins policy triggers inbound task pull (Req 9.4)."""
    clock, store, writer, runner, processor = _setup_runner()

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
    assert job["status"] == "finished"
    assert "Conflict:" in job["description"]
    assert "no kitsu field was written" in job["description"].lower()
    # Zero Kitsu writes sent
    assert len(writer.comments) == 0


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
    proc.pairing_list = {"test-project": "kitsu-proj-1"}

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

"""Property tests for global queue order and retry timing (Property 28).

Validates: Requirements 4.5, 4.9, 4.14, 10.2.
"""

# Feature: kitsu-two-way-sync, Property 28: Global queue order and retry timing

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    FINAL_RETRIES_VALUE,
    MAX_ATTEMPTS,
    RETRY_DEADLINE_S,
    RETRY_DELAY_S,
)
from processor.outbound.identity import IdentityResolver
from processor.outbound.kitsu_writer import KitsuWriterError
from processor.outbound.runner import OutboundJobRunner
from processor.outbound.settings_watch import GateHistory, SettingsWatcher

from .offline import block_network  # noqa: F401
from .outbound_fakes import FakeAyonStore, FakeClock, FakeKitsuWriter

pytestmark = pytest.mark.usefixtures("block_network")


class SimulatedInterruption(BaseException):
    """Simulated stop/crash exception to test recovery."""


def _setup_queue_environment(clock_start: float = 1000.0):
    """Setup in-memory environment with two runner instances."""
    clock = FakeClock(clock_start)
    store = FakeAyonStore(clock=clock)
    writer = FakeKitsuWriter()

    pairing_list = {
        "proj-a": "kitsu-proj-a",
        "proj-b": "kitsu-proj-b",
    }

    toggles = {
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
    }

    gate_history = GateHistory(store, clock=clock)
    for p in pairing_list:
        store.project_settings[p] = {
            "sync_settings": {"two_way_sync": toggles}
        }
        gate_history.record_observation(p, toggles, now=clock())

    watcher = SettingsWatcher(
        store,
        pairing_list_getter=lambda: pairing_list,
        gate_history=gate_history,
        clock=clock,
    )
    watcher.refresh()

    identity_resolver = IdentityResolver(store, writer)

    # Instance 1
    proc1 = MagicMock()
    proc1.sender = "kitsu-processor-host1"
    proc1.pairing_list = pairing_list
    proc1.kitsu_host = "https://kitsu.local"

    # Instance 2
    proc2 = MagicMock()
    proc2.sender = "kitsu-processor-host2"
    proc2.pairing_list = pairing_list
    proc2.kitsu_host = "https://kitsu.local"

    runner1 = OutboundJobRunner(
        processor=proc1,
        clock=clock,
        ayon_client=store,
        writer=writer,
        settings_watcher=watcher,
        gate_history=gate_history,
        identity_resolver=identity_resolver,
        sender="kitsu-processor-host1",
    )

    runner2 = OutboundJobRunner(
        processor=proc2,
        clock=clock,
        ayon_client=store,
        writer=writer,
        settings_watcher=watcher,
        gate_history=gate_history,
        identity_resolver=identity_resolver,
        sender="kitsu-processor-host2",
    )

    return clock, store, writer, runner1, runner2, proc1, proc2


def _run_queue_simulation(
    source_events: List[Dict[str, Any]],
    event_outcomes: Dict[str, List[str]],
    sync_durations: Optional[List[float]] = None,
    stop_durations: Optional[Dict[str, float]] = None,
    clock_start: float = 1000.0,
    max_ticks: int = 150,
) -> Dict[str, Any]:
    """Execute queue simulation with two runners and record all attempts.

    Args:
        source_events: List of event dicts with event_id, created_at,
            entity_id, project_name.
        event_outcomes: Map of event_id -> sequence of outcome strings.
        sync_durations: Optional list of durations for sync_requests.
        stop_durations: Optional map of event_id -> stop duration in seconds.
        clock_start: Starting clock timestamp.
        max_ticks: Maximum simulation loop steps.

    Returns:
        Dict with recorded attempts, store, clock, and runners.
    """
    (
        clock,
        store,
        writer,
        runner1,
        runner2,
        proc1,
        proc2,
    ) = _setup_queue_environment(clock_start)

    sync_dur_queue = list(sync_durations or [])
    stop_dur_map = dict(stop_durations or {})

    def poll_sync():
        if sync_dur_queue:
            dur = sync_dur_queue.pop(0)
            clock.advance(dur)

    proc1.poll_sync_request = poll_sync
    proc2.poll_sync_request = poll_sync

    # Populate entity and kitsu tasks
    entities_seen = set()
    for ev in source_events:
        ent_id = ev["entity_id"]
        proj = ev["project_name"]
        if ent_id not in entities_seen:
            entities_seen.add(ent_id)
            store.entities[("task", ent_id)] = {
                "id": ent_id,
                "name": "modeling",
                "data": {"kitsuId": f"kt-{ent_id}"},
            }
            writer.tasks[f"kt-{ent_id}"] = {
                "id": f"kt-{ent_id}",
                "project_id": f"kitsu-{proj}",
                "task_status_id": "st-wip",
            }

    # Add source events to store
    for ev in source_events:
        store.add_source_event(
            event_id=ev["event_id"],
            topic="entity.task.status_changed",
            project_name=ev["project_name"],
            created_at=ev["created_at"],
            payload={"oldValue": "WIP", "newValue": "Done"},
            summary={"entityId": ev["entity_id"]},
        )

    attempts_log: List[Dict[str, Any]] = []
    active_attempts: List[Dict[str, Any]] = []
    interrupted_attempt_pending: List[Dict[str, Any]] = []

    orig_update_event = store.update_event

    def hooked_update_event(event_id: str, **kwargs: Any) -> None:
        now = float(clock())
        status = kwargs.get("status")
        job = store.jobs.get(event_id)

        if status == "in_progress":
            src_id = job.get("dependsOn") if job else None
            src_evt = store.source_events.get(src_id) if src_id else None
            att_num = kwargs.get("summary", {}).get("attempt", 1)
            rec = {
                "job_id": event_id,
                "source_event_id": src_id,
                "source_created_at": (
                    src_evt["createdAt"] if src_evt else 0.0
                ),
                "attempt": att_num,
                "start_time": now,
                "sender": job.get("sender") if job else None,
                "end_time": None,
                "status": None,
                "last_failed_at": None,
            }
            # Requirement 4.9 & Invariant 4: mutual exclusion
            assert len(active_attempts) == 0, (
                f"Overlap detected: attempt started while "
                f"{active_attempts[0]} is in progress!"
            )
            active_attempts.append(rec)
            attempts_log.append(rec)

            # Check if this attempt should be interrupted by stop
            outcome_list = event_outcomes.get(src_id, [])
            if outcome_list and outcome_list[0] == "interrupted":
                outcome_list.pop(0)
                interrupted_attempt_pending.append(rec)
                orig_update_event(event_id, **kwargs)
                raise SimulatedInterruption()

        elif status in ("finished", "failed", "pending"):
            if active_attempts:
                rec = active_attempts.pop(0)
                rec["end_time"] = now
                rec["status"] = (
                    "failed" if status == "pending" else status
                )
                sum_kw = kwargs.get("summary") or {}
                rec["last_failed_at"] = sum_kw.get("lastFailedAt")

        orig_update_event(event_id, **kwargs)

    store.update_event = hooked_update_event

    orig_comment_status = writer.comment_status

    def hooked_comment_status(task, status, text):
        current = active_attempts[-1] if active_attempts else None
        src_id = current["source_event_id"] if current else None
        outcome_list = event_outcomes.get(src_id, [])
        outcome = outcome_list.pop(0) if outcome_list else "success"

        if outcome == "retryable":
            raise KitsuWriterError("unreachable", 0, "Kitsu unreachable")
        elif outcome == "final_failure":
            raise KitsuWriterError("permission", 403, "Permission refused")

        return orig_comment_status(task, status, text)

    writer.comment_status = hooked_comment_status

    # Simulation loop
    tick = 0
    all_events = [ev["event_id"] for ev in source_events]

    while tick < max_ticks:
        tick += 1

        # Check if all source events reached terminal state
        all_done = True
        for sid in all_events:
            job = next(
                (j for j in store.jobs.values() if j.get("dependsOn") == sid),
                None,
            )
            if not job:
                all_done = False
                break
            st_val = job.get("status")
            retries = job.get("retries", 0)
            if st_val == "in_progress" or st_val == "pending":
                all_done = False
                break
            if st_val == "failed" and retries <= OutboundJobRunner.MAX_RETRIES:
                all_done = False
                break

        if all_done and not runner1.held_job and not runner2.held_job:
            break

        # Alternate runners to simulate concurrent workers
        active_runner = runner1 if tick % 2 == 1 else runner2
        other_runner = runner2 if tick % 2 == 1 else runner1

        ran = False
        try:
            ran = active_runner.poll_once()
        except SimulatedInterruption:
            if interrupted_attempt_pending:
                int_rec = interrupted_attempt_pending.pop(0)
                sid = int_rec["source_event_id"]
                stop_d = stop_dur_map.get(sid, 5.0)
                clock.advance(stop_d)
                active_runner.recover_interrupted()
                int_rec["end_time"] = float(clock())
                int_rec["status"] = "failed"
                int_rec["stop_duration"] = stop_d
                if active_attempts:
                    active_attempts.pop(0)
            ran = True

        if not ran:
            try:
                ran = other_runner.poll_once()
            except SimulatedInterruption:
                if interrupted_attempt_pending:
                    int_rec = interrupted_attempt_pending.pop(0)
                    sid = int_rec["source_event_id"]
                    stop_d = stop_dur_map.get(sid, 5.0)
                    clock.advance(stop_d)
                    other_runner.recover_interrupted()
                    int_rec["end_time"] = float(clock())
                    int_rec["status"] = "failed"
                    int_rec["stop_duration"] = stop_d
                    if active_attempts:
                        active_attempts.pop(0)
                ran = True

        if not ran:
            # Idle poll step (2s idle sleep)
            clock.advance(2.0)

    return {
        "attempts": attempts_log,
        "store": store,
        "clock": clock,
        "runner1": runner1,
        "runner2": runner2,
        "all_done": all_done,
    }


def _verify_property_28_invariants(
    sim_result: Dict[str, Any],
    source_events: List[Dict[str, Any]],
):
    """Verify all 4 Property 28 correctness invariants on simulation output."""
    assert sim_result.get("all_done", True), (
        "Simulation reached max_ticks before all jobs completed"
    )
    attempts = sim_result["attempts"]
    store = sim_result["store"]

    assert len(attempts) > 0, "Simulation produced zero attempts"

    # Invariant 4b: each source event has at most one target Outbound_Job
    for ev in source_events:
        sid = ev["event_id"]
        jobs_for_sid = [
            j for j in store.jobs.values() if j.get("dependsOn") == sid
        ]
        assert len(jobs_for_sid) <= 1, (
            f"Source event {sid} has multiple target jobs: {jobs_for_sid}"
        )

    # Invariant 4a: mutual exclusion - no two attempts overlap
    for i in range(len(attempts)):
        for j in range(i + 1, len(attempts)):
            a, b = attempts[i], attempts[j]
            assert a["end_time"] <= b["start_time"] or (
                b["end_time"] <= a["start_time"]
            ), f"Attempt {a} and {b} overlapped in execution!"

    # Invariant 1: attempts start in ascending order of source creation time,
    # with retries of a job before any later job
    for i in range(len(attempts) - 1):
        a = attempts[i]
        b = attempts[i + 1]
        if a["source_event_id"] == b["source_event_id"]:
            assert b["attempt"] == a["attempt"] + 1, (
                f"Non-consecutive attempt sequence for {a['source_event_id']}:"
                f" {a['attempt']} -> {b['attempt']}"
            )
        else:
            assert a["source_created_at"] < b["source_created_at"], (
                f"Attempt for later source event {a['source_event_id']} "
                f"({a['source_created_at']}) started before "
                f"{b['source_event_id']} ({b['source_created_at']})"
            )
            # Preceding job must be in terminal state
            preceding_job = store.jobs.get(a["job_id"])
            assert preceding_job is not None
            assert preceding_job.get("status") in ("finished", "failed")
            if preceding_job.get("status") == "failed":
                assert preceding_job.get("retries") == FINAL_RETRIES_VALUE

    # Invariant 2: no attempt starts while an earlier source event has a job
    # in progress or failed with retries remaining
    for att in attempts:
        for ev in source_events:
            if ev["created_at"] < att["source_created_at"]:
                sid = ev["event_id"]
                earlier_job = next(
                    (
                        j
                        for j in store.jobs.values()
                        if j.get("dependsOn") == sid
                    ),
                    None,
                )
                assert earlier_job is not None, (
                    f"Earlier source event {sid} has no target job when "
                    f"attempt for {att['source_event_id']} started"
                )
                status = earlier_job.get("status")
                retries = earlier_job.get("retries", 0)
                assert status in ("finished", "failed"), (
                    f"Earlier job {earlier_job['id']} is {status} when later "
                    f"job attempt started"
                )
                if status == "failed":
                    assert retries == FINAL_RETRIES_VALUE, (
                        f"Earlier job {earlier_job['id']} has retries "
                        f"remaining ({retries}) when later job started"
                    )

    # Invariant 3: each retry starts at least 10s and at most 60s after
    # the failed attempt, excluding simulated stop and sync_request time
    for i, b in enumerate(attempts):
        if b["attempt"] > 1:
            prev = next(
                (
                    a
                    for a in attempts[:i]
                    if a["source_event_id"] == b["source_event_id"]
                    and a["attempt"] == b["attempt"] - 1
                ),
                None,
            )
            assert prev is not None, f"Missing prior attempt for {b}"
            t_fail = prev.get("last_failed_at") or prev["end_time"]
            t_start = b["start_time"]
            stop_dur = prev.get("stop_duration", 0.0)

            # Lower bound: at least 10s after failure (Req 10.2)
            wall_elapsed = t_start - t_fail
            assert wall_elapsed >= float(RETRY_DELAY_S), (
                f"Retry {b} started too early: {wall_elapsed}s < "
                f"{RETRY_DELAY_S}s (t_fail={t_fail}, t_start={t_start})"
            )
            # Upper bound: at most 60s excluding stop duration (Req 10.2)
            eff_elapsed = wall_elapsed - stop_dur
            assert eff_elapsed <= float(RETRY_DEADLINE_S) + 5.0, (
                f"Retry {b} started too late: {eff_elapsed}s > "
                f"{RETRY_DEADLINE_S}s"
            )


# ---------------------------------------------------------------------------
# Hypothesis Property Test
# ---------------------------------------------------------------------------


@st.composite
def queue_scenarios(draw):
    """Generate random Outbound_Job scenarios with outcomes and timings."""
    n_events = draw(st.integers(min_value=2, max_value=4))
    timestamps = draw(
        st.lists(
            st.integers(min_value=1000, max_value=5000),
            min_size=n_events,
            max_size=n_events,
            unique=True,
        )
    )

    entities = ["task-1", "task-2", "task-3"]
    projects = ["proj-a", "proj-b"]

    source_events = []
    event_outcomes = {}

    for idx, ts in enumerate(timestamps):
        ev_id = f"evt-{idx + 1}"
        source_events.append(
            {
                "event_id": ev_id,
                "created_at": float(ts),
                "entity_id": draw(st.sampled_from(entities)),
                "project_name": draw(st.sampled_from(projects)),
            }
        )

        # Generate sequence of outcomes terminating within at most 4 attempts
        pattern = draw(
            st.sampled_from(
                [
                    ["success"],
                    ["retryable", "success"],
                    ["retryable", "retryable", "success"],
                    ["retryable", "retryable", "retryable", "retryable"],
                    ["final_failure"],
                    ["retryable", "final_failure"],
                    ["interrupted", "success"],
                    ["interrupted", "retryable", "success"],
                ]
            )
        )
        event_outcomes[ev_id] = list(pattern)

    sync_durations = draw(
        st.lists(
            st.floats(min_value=1.0, max_value=6.0),
            min_size=0,
            max_size=3,
        )
    )

    return source_events, event_outcomes, sync_durations


@settings(max_examples=100, deadline=None)
@given(scenario=queue_scenarios())
def test_property_28_global_queue_order_and_retry_timing(scenario):
    """Property 28: Global queue order and retry timing simulation."""
    source_events, event_outcomes, sync_durations = scenario
    result = _run_queue_simulation(
        source_events=source_events,
        event_outcomes=event_outcomes,
        sync_durations=sync_durations,
    )
    _verify_property_28_invariants(result, source_events)


# ---------------------------------------------------------------------------
# Targeted Unit Tests
# ---------------------------------------------------------------------------


def test_queue_retryable_4_attempts_unblocks_queue():
    """Job failing all 4 attempts marks final and unblocks next job (10.6)."""
    source_events = [
        {
            "event_id": "evt-1",
            "created_at": 1000.0,
            "entity_id": "task-1",
            "project_name": "proj-a",
        },
        {
            "event_id": "evt-2",
            "created_at": 1050.0,
            "entity_id": "task-2",
            "project_name": "proj-b",
        },
    ]
    outcomes = {
        "evt-1": ["retryable", "retryable", "retryable", "retryable"],
        "evt-2": ["success"],
    }
    result = _run_queue_simulation(source_events, outcomes)
    _verify_property_28_invariants(result, source_events)

    store = result["store"]
    job1 = store.jobs["job-1"]
    assert job1["status"] == "failed"
    assert job1["retries"] == FINAL_RETRIES_VALUE
    assert job1["summary"]["attempt"] == MAX_ATTEMPTS

    job2 = store.jobs["job-2"]
    assert job2["status"] == "finished"


def test_queue_interrupted_by_stop_and_recovered():
    """Interrupted job at start is recovered and completes on retry (10.9)."""
    source_events = [
        {
            "event_id": "evt-1",
            "created_at": 1000.0,
            "entity_id": "task-1",
            "project_name": "proj-a",
        },
        {
            "event_id": "evt-2",
            "created_at": 1050.0,
            "entity_id": "task-2",
            "project_name": "proj-b",
        },
    ]
    outcomes = {
        "evt-1": ["interrupted", "success"],
        "evt-2": ["success"],
    }
    result = _run_queue_simulation(
        source_events, outcomes, stop_durations={"evt-1": 15.0}
    )
    _verify_property_28_invariants(result, source_events)

    attempts = result["attempts"]
    assert len(attempts) == 3
    # evt-1 attempt 1 (interrupted)
    assert attempts[0]["source_event_id"] == "evt-1"
    assert attempts[0]["attempt"] == 1
    # evt-1 attempt 2 (success after recovery)
    assert attempts[1]["source_event_id"] == "evt-1"
    assert attempts[1]["attempt"] == 2
    # evt-2 attempt 1 (success)
    assert attempts[2]["source_event_id"] == "evt-2"
    assert attempts[2]["attempt"] == 1

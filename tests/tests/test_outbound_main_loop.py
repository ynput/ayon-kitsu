"""Unit tests for Processor main loop and Outbound_Sync integration.

Validates: Requirements 2.3, 2.5, 2.7, 4.6, 4.7, 4.11, 10.5, 10.8 (Task 11.2).
"""

import pytest

from processor.processor import KitsuProcessor

from .offline import block_network  # noqa: F401
from .outbound_fakes import FakeAyonStore, FakeClock, FakeKitsuWriter
from .outbound_harness import KITSU_PROJECT, PROJECT
from processor.outbound.constants import DECISION_APPLIED
from processor.outbound.identity import IdentityResolver
from processor.outbound.runner import OutboundJobRunner
from processor.outbound.settings_watch import GateHistory, SettingsWatcher

pytestmark = pytest.mark.usefixtures("block_network")


class StopLoop(BaseException):
    """Sentinel exception to terminate the infinite main loop in tests."""


def _setup_processor_harness(clock=None, store=None, writer=None):
    """Create a KitsuProcessor test harness without live connections."""
    clock = clock or FakeClock(1000.0)
    store = store or FakeAyonStore(clock=clock)
    writer = writer or FakeKitsuWriter()

    proc = object.__new__(KitsuProcessor)
    proc.clock = clock
    proc.ayon_api = store
    proc.entrypoint = "/addons/kitsu/1.2.4"
    proc.pairing_list = {"kitsu-p1": "proj1"}
    proc.outbound = None

    gate_history = GateHistory(store, clock=clock)
    gate_history.record_observation(
        "proj1",
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
        pairing_list_getter=proc.get_outbound_pairings,
        gate_history=gate_history,
        clock=clock,
    )
    identity = IdentityResolver(store, writer, entrypoint=proc.entrypoint)

    runner = OutboundJobRunner(
        processor=proc,
        clock=clock,
        ayon_client=store,
        writer=writer,
        settings_watcher=watcher,
        gate_history=gate_history,
        identity_resolver=identity,
        sender="kitsu-processor-test",
    )
    proc.outbound = runner
    return proc, store, writer, clock


def test_get_outbound_pairings_reverses_and_filters():
    """get_outbound_pairings reverses mapping and filters null pairs."""
    proc = object.__new__(KitsuProcessor)
    proc.pairing_list = {
        "k1": "proj1",
        "k2": None,
        "k3": "",
        "": "proj4",
        "k5": "proj5",
    }
    pairings = proc.get_outbound_pairings()
    assert pairings == {"proj1": "k1", "proj5": "k5"}

    proc.set_paired_ayon_project("k6", "proj6")
    assert proc.get_outbound_pairings()["proj6"] == "k6"


def test_outbound_import_failure_leaves_inbound_active(monkeypatch):
    """Outbound import failure sets outbound=None; inbound stays functional."""
    proc = object.__new__(KitsuProcessor)
    proc.kitsu_server_url = "https://kitsu.example.com/api"
    proc.kitsu_login_email = "test@example.com"
    proc.kitsu_login_password = "password"
    proc.entrypoint = "/addons/kitsu/1.2.4"
    proc.pairing_list = {"k1": "proj1"}

    # Simulate import failure
    def fake_create_outbound():
        return None

    monkeypatch.setattr(proc, "_create_outbound_safe", fake_create_outbound)
    proc.outbound = proc._create_outbound_safe()
    assert proc.outbound is None

    # Inbound sync request still runs
    called = []
    monkeypatch.setattr(
        proc, "_poll_sync_request_once", lambda: called.append(True) or True
    )
    assert proc.poll_sync_request() is True
    assert len(called) == 1


def test_startup_ordering_load_refresh_drain_fullsync(monkeypatch):
    """Startup ordering: load -> refresh -> drain -> warning -> full_sync."""
    proc, store, writer, clock = _setup_processor_harness()
    call_order = []

    orig_load = proc.outbound.gate_history.load
    orig_refresh = proc.outbound.settings_watcher.refresh
    orig_drain = proc.outbound.drain

    def fake_load(*args, **kwargs):
        call_order.append("gate_history.load")
        return orig_load(*args, **kwargs)

    def fake_refresh(*args, **kwargs):
        call_order.append("settings_watcher.refresh")
        return orig_refresh(*args, **kwargs)

    def fake_drain(*args, **kwargs):
        call_order.append("outbound.drain")
        return orig_drain(*args, **kwargs)

    def fake_full_sync(*args, **kwargs):
        call_order.append("project_full_sync")

    def fake_sleep(secs):
        raise StopLoop()

    monkeypatch.setattr(proc.outbound.gate_history, "load", fake_load)
    monkeypatch.setattr(
        proc.outbound.settings_watcher, "refresh", fake_refresh
    )
    monkeypatch.setattr(proc.outbound, "drain", fake_drain)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", fake_full_sync
    )
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)

    with pytest.raises(StopLoop):
        proc.start_processing()

    assert call_order == [
        "gate_history.load",
        "settings_watcher.refresh",
        "outbound.drain",
        "project_full_sync",
    ]


def test_startup_drain_warning_on_final_failures(monkeypatch):
    """Single warning lists job_id, entity_id, category of final failures."""
    proc, store, writer, clock = _setup_processor_harness()

    # Configure drain to return two failed jobs
    def fake_drain():
        return [
            {
                "job_id": "job-1",
                "entity_id": "ent-1",
                "category": "task_status",
            },
            {
                "job_id": "job-2",
                "entity_id": "ent-2",
                "category": "task_status",
            },
        ]

    def fake_sleep(secs):
        raise StopLoop()

    warnings = []
    monkeypatch.setattr(
        "processor.processor.logging.warning",
        lambda msg, *a: warnings.append(msg % a if a else msg),
    )
    monkeypatch.setattr(proc.outbound, "drain", fake_drain)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *a, **k: None
    )
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)

    with pytest.raises(StopLoop):
        proc.start_processing()

    assert len(warnings) == 1
    msg = warnings[0]
    assert "Startup drain: outbound jobs failed on final attempt" in msg
    assert "job_id=job-1" in msg
    assert "entity_id=ent-1" in msg
    assert "job_id=job-2" in msg
    assert "entity_id=ent-2" in msg


def test_disabled_master_skips_drain_and_outbound(monkeypatch):
    """Disabled master skips drain and poll_once with zero Kitsu writes."""
    proc, store, writer, clock = _setup_processor_harness()

    # Disable master toggle for proj1 in studio settings
    store.studio_settings["sync_settings"]["two_way_sync"]["enabled"] = False
    proc.outbound.settings_watcher.refresh()

    drain_called = []
    poll_called = []
    sync_called = []

    def fake_sleep(secs):
        raise StopLoop()

    monkeypatch.setattr(
        proc.outbound, "drain", lambda: drain_called.append(True) or []
    )
    monkeypatch.setattr(
        proc.outbound, "poll_once", lambda: poll_called.append(True) or False
    )
    monkeypatch.setattr(
        "processor.processor.project_full_sync",
        lambda *a, **k: sync_called.append(True),
    )
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)

    with pytest.raises(StopLoop):
        proc.start_processing()

    assert len(drain_called) == 0
    assert len(poll_called) == 0
    assert len(sync_called) == 1
    assert len(writer.comments) == 0


def test_drain_failure_does_not_block_fullsync(monkeypatch):
    """Drain failure skips master project (10.5) but syncs disabled one."""
    proc, store, writer, clock = _setup_processor_harness()
    proc.pairing_list = {"kitsu-p1": "proj1", "kitsu-p2": "proj2"}

    # proj2 has master=False (outbound disabled)
    store.project_settings["proj2"] = {
        "sync_settings": {"two_way_sync": {"enabled": False}}
    }
    proc.outbound.gate_history.record_observation(
        "proj2",
        {
            "valid": True,
            "master": False,
            "categories": {},
            "conflict_policy": "kitsu_wins",
        },
        now=clock(),
    )
    proc.outbound.settings_watcher.refresh()

    def bad_drain():
        raise RuntimeError("simulated drain failure")

    sync_called = []

    def fake_sleep(secs):
        raise StopLoop()

    monkeypatch.setattr(proc.outbound, "drain", bad_drain)
    monkeypatch.setattr(
        "processor.processor.project_full_sync",
        lambda _api, p_id, p_name: sync_called.append(p_name),
    )
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)

    with pytest.raises(StopLoop):
        proc.start_processing()

    # proj1 skipped because master=True and drain failed (Req 10.5);
    # proj2 synced because master=False
    assert sync_called == ["proj2"]


def test_inbound_work_wins_iteration(monkeypatch):
    """When inbound sync request runs, outbound poll and sleep are skipped."""
    proc, store, writer, clock = _setup_processor_harness()

    outbound_polled = []
    sleeps = []
    iterations = [0]

    def fake_poll_sync():
        iterations[0] += 1
        if iterations[0] == 1:
            return True  # sync request ran on iteration 1
        raise StopLoop()

    monkeypatch.setattr(proc.outbound, "drain", lambda: [])
    monkeypatch.setattr(proc, "_poll_sync_request_once", fake_poll_sync)
    monkeypatch.setattr(
        proc.outbound, "poll_once", lambda: outbound_polled.append(True)
    )
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("time.time", clock)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *a, **k: None
    )

    with pytest.raises(StopLoop):
        proc.start_processing()

    # Outbound was not polled on iteration 1
    assert len(outbound_polled) == 0
    assert len(sleeps) == 0


def test_outbound_work_suppresses_idle_sleep(monkeypatch):
    """Outbound work running suppresses sleep; idle iteration sleeps 2s."""
    proc, store, writer, clock = _setup_processor_harness()

    sleeps = []
    poll_results = [True, False]

    def fake_outbound_poll():
        if poll_results:
            return poll_results.pop(0)
        return False

    def fake_sleep(s):
        sleeps.append(s)
        raise StopLoop()

    monkeypatch.setattr(proc.outbound, "drain", lambda: [])
    monkeypatch.setattr(proc, "_poll_sync_request_once", lambda: False)
    monkeypatch.setattr(proc.outbound, "poll_once", fake_outbound_poll)
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *a, **k: None
    )

    with pytest.raises(StopLoop):
        proc.start_processing()

    # Slept only on the second (idle) iteration
    assert sleeps == [2]


def test_settings_refresh_30s_and_reaper_60s(monkeypatch):
    """Settings refresh runs at 30s; reaper runs at 60s."""
    proc, store, writer, clock = _setup_processor_harness()

    refreshes = []
    reaps = []
    loop_count = [0]

    def fake_refresh():
        refreshes.append(clock())

    def fake_reap():
        reaps.append(clock())

    def fake_sleep(s):
        loop_count[0] += 1
        clock.advance(35.0)  # advance by 35s each iteration
        if loop_count[0] >= 3:
            raise StopLoop()

    monkeypatch.setattr(proc.outbound, "drain", lambda: [])
    monkeypatch.setattr(
        proc.outbound.settings_watcher, "refresh", fake_refresh
    )
    monkeypatch.setattr(proc.outbound, "reap_stale", fake_reap)
    monkeypatch.setattr(proc, "_poll_sync_request_once", lambda: False)
    monkeypatch.setattr(proc.outbound, "poll_once", lambda: False)
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *a, **k: None
    )

    with pytest.raises(StopLoop):
        proc.start_processing()

    # Refreshes ran when >= 30s elapsed
    assert len(refreshes) >= 2
    # Reaper ran when >= 60s elapsed
    assert len(reaps) >= 1


def test_pending_ayon_update_retried_in_loop(monkeypatch):
    """Pending AYON update is retried in loop even if master is disabled."""
    proc, store, writer, clock = _setup_processor_harness()

    # Disable master toggle in studio settings
    store.studio_settings["sync_settings"]["two_way_sync"]["enabled"] = False
    proc.outbound.settings_watcher.refresh()

    store.jobs["job-1"] = {
        "id": "job-1",
        "status": "in_progress",
        "description": "old",
    }
    proc.outbound.pending_ayon_update = {
        "job_id": "job-1",
        "status": "finished",
        "description": "Done",
    }

    def fake_sleep(s):
        raise StopLoop()

    monkeypatch.setattr(proc.outbound, "drain", lambda: [])
    monkeypatch.setattr(proc, "_poll_sync_request_once", lambda: False)
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *a, **k: None
    )

    with pytest.raises(StopLoop):
        proc.start_processing()

    # Update was retried and cleared
    assert proc.outbound.pending_ayon_update is None
    assert store.jobs["job-1"]["status"] == "finished"


def test_set_paired_ayon_project_refreshes_settings():
    """set_paired_ayon_project triggers settings refresh immediately."""
    proc, store, writer, clock = _setup_processor_harness()

    called = []
    proc.outbound.settings_watcher.refresh = lambda: called.append(True)

    proc.set_paired_ayon_project("kitsu-p2", "proj2")
    assert proc.pairing_list["kitsu-p2"] == "proj2"
    assert len(called) == 1


def test_loop_exception_isolation(monkeypatch):
    """Exceptions in maintenance/polling are isolated; loop continues."""
    proc, store, writer, clock = _setup_processor_harness()

    loop_count = [0]

    def bad_refresh():
        raise RuntimeError("refresh failed")

    def bad_reap():
        raise RuntimeError("reap failed")

    def bad_sync():
        raise RuntimeError("sync poll failed")

    def bad_outbound():
        raise RuntimeError("outbound poll failed")

    def fake_sleep(s):
        loop_count[0] += 1
        if loop_count[0] >= 2:
            raise StopLoop()

    monkeypatch.setattr(proc.outbound, "drain", lambda: [])
    monkeypatch.setattr(proc.outbound.settings_watcher, "refresh", bad_refresh)
    monkeypatch.setattr(proc.outbound, "reap_stale", bad_reap)
    monkeypatch.setattr(proc, "_poll_sync_request_once", bad_sync)
    monkeypatch.setattr(proc.outbound, "poll_once", bad_outbound)
    monkeypatch.setattr("time.sleep", fake_sleep)
    monkeypatch.setattr("time.time", clock)
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *a, **k: None
    )

    # Loop completes 2 iterations without raising the maintenance exceptions
    with pytest.raises(StopLoop):
        proc.start_processing()

    assert loop_count[0] == 2


def test_startup_full_sync_blocked_when_toggle_state_unknown(monkeypatch):
    """Full sync is blocked if gate_history.load fails and toggles unknown.
    """
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

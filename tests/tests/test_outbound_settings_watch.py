"""Unit tests for SettingsWatcher and GateHistory (Task 9.2).

Validates: Requirements 2.7, 2.10, 4.7, 4.12, 4.13.
"""

import logging
from unittest.mock import MagicMock
import pytest

from processor.outbound.constants import GATE_TOPIC
from processor.outbound.settings_watch import GateHistory, SettingsWatcher

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


class FakeClock:
    """Controllable clock for deterministic time testing."""

    def __init__(self, start: float = 1000.0):
        self.current_time = float(start)

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += float(seconds)


class FakeAyonClient:
    """In-memory AYON API client mock."""

    def __init__(self):
        self.studio_settings = {
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
        self.project_settings = {}
        self.events = []
        self.event_counter = 0

    def get_service_addon_settings(self, project_name=None):
        if project_name is None:
            return self.studio_settings
        return self.project_settings.get(project_name, {})

    def get_events(self, topics=None, **kwargs):
        if not topics:
            return list(self.events)
        topic_set = set(topics)
        return [e for e in self.events if e.get("topic") in topic_set]

    def dispatch_event(self, topic, project_name=None, summary=None, **kwargs):
        self.event_counter += 1
        event_id = f"evt-{self.event_counter}"
        event = {
            "id": event_id,
            "topic": topic,
            "project_name": project_name,
            "summary": summary or {},
        }
        self.events.append(event)
        res = MagicMock()
        res.data = {"id": event_id}
        return res

    def update_event(self, event_id, summary=None, **kwargs):
        for e in self.events:
            if e.get("id") == event_id:
                if summary:
                    e.setdefault("summary", {}).update(summary)
                return


def test_settings_watch_refresh_within_60s():
    """Settings watcher queries and updates effective toggles (Req 2.7)."""
    clock = FakeClock(1000.0)
    ayon = FakeAyonClient()
    gate_history = GateHistory(ayon, clock=clock)
    watcher = SettingsWatcher(
        ayon,
        pairing_list_getter=lambda: {"proj1": "kitsu-proj-1"},
        gate_history=gate_history,
        clock=clock,
    )

    toggles1 = watcher.refresh()
    assert "proj1" in toggles1
    assert toggles1["proj1"]["categories"]["task_status"] is True
    assert toggles1["proj1"]["categories"]["task_assignees"] is False

    # Simulate settings change in AYON within 60s
    clock.advance(30.0)
    ayon.project_settings["proj1"] = {
        "sync_settings": {
            "two_way_sync": {
                "task_assignees": True,
            }
        }
    }

    toggles2 = watcher.refresh()
    assert toggles2["proj1"]["categories"]["task_assignees"] is True
    assert watcher.last_refresh_time == 1030.0


def test_heartbeat_updates_last_observed_at():
    """Heartbeat updates summary.lastObservedAt on the latest gate event."""
    clock = FakeClock(1000.0)
    ayon = FakeAyonClient()
    gate_history = GateHistory(ayon, clock=clock)
    watcher = SettingsWatcher(
        ayon,
        pairing_list_getter=lambda: {"proj1": "kitsu-proj-1"},
        gate_history=gate_history,
        clock=clock,
    )

    watcher.refresh()
    assert gate_history.latest_gate_event_id == "evt-1"
    evt1 = [e for e in ayon.events if e["id"] == "evt-1"][0]
    assert evt1["summary"]["lastObservedAt"] == 1000.0

    clock.advance(30.0)
    watcher.refresh()
    assert evt1["summary"]["lastObservedAt"] == 1030.0


def test_snapshot_persisted_on_change():
    """Snapshots are persisted only when effective toggles change."""
    clock = FakeClock(1000.0)
    ayon = FakeAyonClient()
    gate_history = GateHistory(ayon, clock=clock)
    watcher = SettingsWatcher(
        ayon,
        pairing_list_getter=lambda: {"proj1": "kitsu-proj-1"},
        gate_history=gate_history,
        clock=clock,
    )

    watcher.refresh()
    snapshots = [e for e in ayon.events if e["topic"] == GATE_TOPIC]
    assert len(snapshots) == 1

    # Second refresh with no changes: no new snapshot event
    clock.advance(30.0)
    watcher.refresh()
    snapshots = [e for e in ayon.events if e["topic"] == GATE_TOPIC]
    assert len(snapshots) == 1

    # Change settings: new snapshot event dispatched
    clock.advance(30.0)
    ayon.project_settings["proj1"] = {
        "sync_settings": {
            "two_way_sync": {
                "enabled": False,
            }
        }
    }
    watcher.refresh()
    snapshots = [e for e in ayon.events if e["topic"] == GATE_TOPIC]
    assert len(snapshots) == 2


def test_gap_marker_with_settings_changed_event():
    """Gap marker marks unknown=True with settings.changed event (Req 4.12)."""
    clock = FakeClock(2000.0)
    ayon = FakeAyonClient()
    # Prior run's gate event
    ayon.events.append(
        {
            "id": "gate-old",
            "topic": GATE_TOPIC,
            "summary": {
                "project": "proj1",
                "toggles": {"master": True, "categories": {}},
                "lastObservedAt": 1000.0,
            },
        }
    )
    # settings.changed event during stop
    ayon.events.append(
        {
            "id": "ch-1",
            "topic": "settings.changed",
            "created_at": 1500.0,
            "summary": {"addon_name": "kitsu"},
        }
    )

    gate_history = GateHistory(ayon, clock=clock)
    gap = gate_history.load(started_at=2000.0)

    assert gap is not None
    assert gap["unknown"] is True
    assert gap["durationS"] == 1000.0
    assert gap["settingsChanges"] == 1

    # Verified gap marker dispatched
    gap_events = [
        e
        for e in ayon.events
        if e["topic"] == GATE_TOPIC and "gap" in e.get("summary", {})
    ]
    assert len(gap_events) == 1

    # toggles_at for event created during gap returns unknown_gap
    state = gate_history.toggles_at("proj1", 1500.0)
    assert state["state"] == "unknown_gap"
    assert state["toggles"] is None


def test_gap_marker_without_settings_changed_event():
    """Gap marker marks unknown=False without settings.changed event."""
    clock = FakeClock(2000.0)
    ayon = FakeAyonClient()
    ayon.events.append(
        {
            "id": "gate-old",
            "topic": GATE_TOPIC,
            "summary": {
                "project": "proj1",
                "toggles": {
                    "master": True,
                    "categories": {"task_status": True},
                },
                "observedAt": 1000.0,
                "lastObservedAt": 1000.0,
            },
        }
    )

    gate_history = GateHistory(ayon, clock=clock)
    gap = gate_history.load(started_at=2000.0)

    assert gap is not None
    assert gap["unknown"] is False
    assert gap["settingsChanges"] == 0

    # toggles_at for event created during stop returns previous snapshot
    state = gate_history.toggles_at("proj1", 1500.0)
    assert state["state"] == "snapshot"
    assert state["toggles"]["master"] is True


def test_gap_skip_tracking():
    """Skipped events count is incremented on gap marker (Req 4.13)."""
    clock = FakeClock(2000.0)
    ayon = FakeAyonClient()
    ayon.events.append(
        {
            "id": "gate-old",
            "topic": GATE_TOPIC,
            "summary": {
                "project": "proj1",
                "toggles": {},
                "lastObservedAt": 1000.0,
            },
        }
    )
    ayon.events.append(
        {
            "id": "ch-1",
            "topic": "settings.changed",
            "created_at": 1500.0,
            "summary": {"addon_name": "kitsu"},
        }
    )

    gate_history = GateHistory(ayon, clock=clock)
    gate_history.load(started_at=2000.0)

    gate_history.record_gap_skip()
    assert gate_history.skipped_events_count == 1
    gap_evt = [e for e in ayon.events if e.get("id") == "evt-1"][0]
    assert gap_evt["summary"]["skippedEvents"] == 1


def test_invalid_settings_logged(caplog):
    """Invalid settings log ERROR with project and setting path (Req 2.10)."""
    clock = FakeClock(1000.0)
    ayon = FakeAyonClient()
    ayon.project_settings["proj1"] = {
        "sync_settings": {
            "two_way_sync": {
                "enabled": "not_a_bool",
            }
        }
    }
    watcher = SettingsWatcher(
        ayon,
        pairing_list_getter=lambda: {"proj1": "kitsu-proj-1"},
        clock=clock,
    )

    with caplog.at_level(logging.ERROR):
        toggles = watcher.refresh()

    assert toggles["proj1"]["valid"] is False
    assert toggles["proj1"]["master"] is False
    assert any(
        "Invalid Two_Way_Sync_Settings for project proj1" in r.message
        for r in caplog.records
    )

"""Bounded-echo checks that drive the real OutboundJobRunner.

``EchoSimulator`` re-implements the outbound handlers. These tests
instead run the production runner and handler against the in-memory
fakes. Only the addon server's inbound ``/push`` is simulated, because
it cannot run offline. Echo events it emits carry the real sync markers
so the runner's origin classification is exercised too.
"""

from typing import Any, Dict, List

import pytest

from processor.outbound.constants import TOPIC_TASK_STATUS_CHANGED
from processor.outbound.mapping import kitsu_status_to_ayon

from .offline import block_network  # noqa: F401
from .outbound_harness import (
    KITSU_PROJECT,
    PROJECT,
    add_event,
    build_runner,
)
from .outbound_sim import sync_event

pytestmark = pytest.mark.usefixtures("block_network")

TASK_ID = "task-1"
KITSU_TASK_ID = "kt-task-1"


class StatusEchoRig:
    """Real runner plus a minimal inbound status echo."""

    def __init__(self, ayon_status: str, kitsu_status: str, policy: str):
        statuses: List[Dict[str, Any]] = [
            {"id": f"id-{n}", "name": n, "archived": False}
            for n in ("A", "B", "C")
        ]
        harness = build_runner(policy=policy)
        self.__dict__.update(harness.__dict__)
        self.writer.statuses = statuses
        self.store.entities[("task", TASK_ID)] = {
            "id": TASK_ID,
            "name": "animation",
            "status": ayon_status,
            "data": {"kitsuId": KITSU_TASK_ID},
        }
        self.writer.tasks[KITSU_TASK_ID] = {
            "id": KITSU_TASK_ID,
            "project_id": KITSU_PROJECT,
            "task_status_id": f"id-{kitsu_status}",
        }
        self.processor.pull_kitsu_task = self.inbound_pull
        self.ayon_writes = 0
        self._event_no = 0
        self._comments_seen = 0

    @property
    def kitsu_writes(self) -> int:
        """Number of status comments written to Kitsu."""
        return len(self.writer.comments)

    @property
    def ayon_status(self) -> str:
        return self.store.entities[("task", TASK_ID)]["status"]

    @property
    def kitsu_status_id(self) -> str:
        return self.writer.tasks[KITSU_TASK_ID]["task_status_id"]

    def user_changes_status(self, new_status: str) -> None:
        """Change the AYON status as a user and emit the event."""
        entity = self.store.entities[("task", TASK_ID)]
        old, entity["status"] = entity["status"], new_status
        self._emit(
            f"evt-user-{self._next()}",
            payload={"oldValue": old, "newValue": new_status},
            user="bob",
        )

    def inbound_pull(self, kitsu_id: str, kitsu_task: Any = None) -> None:
        """Simulate the addon applying the current Kitsu status."""
        current = self.writer.tasks[kitsu_id]["task_status_id"]
        status = next(s for s in self.writer.statuses if s["id"] == current)
        wanted = kitsu_status_to_ayon(status)
        entity = self.store.entities[("task", TASK_ID)]
        old = entity["status"]
        if old == wanted:
            return
        entity["status"] = wanted
        self.ayon_writes += 1
        marked = sync_event(
            id=f"evt-sync-{self._next()}",
            topic=TOPIC_TASK_STATUS_CHANGED,
            project=PROJECT,
            createdAt=self.clock(),
            user=None,
            sender="kitsu-server-addon",
            summary={"entityId": TASK_ID},
            payload={"oldValue": old, "newValue": wanted},
        )
        self.store.add_source_event(
            event_id=marked["id"],
            topic=marked["topic"],
            project_name=PROJECT,
            created_at=marked["createdAt"] + self._event_no,
            payload=marked["payload"],
            summary=marked["summary"],
            user=None,
            sender=marked["sender"],
            sender_type=marked["sender_type"],
        )

    def run_until_quiescent(self, max_steps: int = 50) -> int:
        """Poll the runner, echoing each new Kitsu write inbound."""
        steps = 0
        while self.runner.poll_once():
            steps += 1
            assert steps <= max_steps, "echo did not settle"
            if self.kitsu_writes > self._comments_seen:
                self._comments_seen = self.kitsu_writes
                self.inbound_pull(KITSU_TASK_ID)
        return steps

    def _next(self) -> int:
        self._event_no += 1
        return self._event_no

    def _emit(self, event_id: str, payload: Dict[str, Any], user: str):
        add_event(
            self.store,
            event_id,
            TOPIC_TASK_STATUS_CHANGED,
            TASK_ID,
            created_at=self.clock() + self._event_no,
            payload=payload,
        ).update(user=user)


@pytest.mark.parametrize(
    "kitsu_curr,prev,new,policy,expected_kwrites,expected_awrites,final",
    [
        ("A", "A", "B", "kitsu_wins", 1, 0, "B"),
        ("A", "A", "B", "ayon_wins", 1, 0, "B"),
        ("B", "A", "B", "kitsu_wins", 0, 0, "B"),
        ("B", "A", "B", "ayon_wins", 0, 0, "B"),
        ("C", "A", "B", "ayon_wins", 1, 0, "B"),
        ("C", "A", "B", "kitsu_wins", 0, 1, "C"),
    ],
)
def test_status_echo_matrix_with_real_runner(
    kitsu_curr, prev, new, policy, expected_kwrites, expected_awrites, final
):
    """Same decision matrix as the simulator test, on production code."""
    rig = StatusEchoRig(prev, kitsu_curr, policy)
    rig.user_changes_status(new)

    assert rig.run_until_quiescent() > 0

    assert rig.kitsu_writes == expected_kwrites
    assert rig.ayon_writes == expected_awrites
    assert rig.ayon_status == final
    assert rig.kitsu_status_id == f"id-{final}"

    # Time passing must not produce more writes.
    rig.clock.advance(60.0)
    assert rig.run_until_quiescent() == 0
    assert rig.kitsu_writes == expected_kwrites
    assert rig.ayon_writes == expected_awrites

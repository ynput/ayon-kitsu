"""Echo rigs that drive the real OutboundJobRunner.

Each rig wires the production runner and handlers to the in-memory
fakes and simulates only the addon server's inbound ``/push`` (which
cannot run offline). The simulated inbound emits events carrying the
real sync markers, so the runner's origin classification is exercised.

``EchoSimulator`` re-implements the outbound handlers instead, so it
cannot detect bugs in the production handlers.
"""

from typing import Any, Dict, List, Optional, Tuple

from processor.outbound.constants import (
    TOPIC_FOLDER_ATTRIB_CHANGED,
    TOPIC_TASK_ASSIGNEES_CHANGED,
    TOPIC_TASK_STATUS_CHANGED,
)
from processor.outbound.inbound_mirror import match_assignees_by_email
from processor.outbound.mapping import (
    kitsu_attrib_view,
    kitsu_status_to_ayon,
)

from .outbound_harness import KITSU_PROJECT, PROJECT, build_runner
from .outbound_sim import sync_event

TASK_ID = "task-1"
FOLDER_ID = "fold-1"
KITSU_ID = "kt-1"


class EchoRig:
    """Real runner plus a simulated inbound echo for one domain."""

    topic = ""
    entity_kind = "task"
    entity_id = TASK_ID
    enable: Tuple[str, ...] = ()
    disable: Tuple[str, ...] = ("task_status",)

    def __init__(self, policy: str = "kitsu_wins") -> None:
        harness = build_runner(
            self.enable, disable=self.disable, policy=policy
        )
        self.__dict__.update(harness.__dict__)
        self.policy = policy
        self.kitsu_writes = 0
        self.ayon_writes = 0
        self._seq = 0
        self.processor.pull_kitsu_task = self.inbound_pull
        self.processor.pull_kitsu_entity = self.inbound_pull
        self.setup()
        self._marker = self._kitsu_marker()

    # -- hooks -----------------------------------------------------
    def setup(self) -> None:
        """Populate the store and writer for this domain."""
        raise NotImplementedError

    def _kitsu_marker(self) -> int:
        """Return a counter that grows on every Kitsu write."""
        raise NotImplementedError

    def _apply_inbound(self) -> Optional[Tuple[Any, Any]]:
        """Apply Kitsu state to AYON; return (old, new) if changed."""
        raise NotImplementedError

    # -- state views -----------------------------------------------
    @property
    def ayon_state(self) -> Dict[str, Any]:
        """Live AYON entity dict."""
        return self.store.entities[(self.entity_kind, self.entity_id)]

    @property
    def kitsu_state(self) -> Dict[str, Any]:
        """Live Kitsu entity dict."""
        return self.writer.tasks[KITSU_ID]

    # -- driving ---------------------------------------------------
    def emit_user_event(
        self, old: Any, new: Any, user: str = "alice"
    ) -> None:
        """Emit a user-originated AYON change event."""
        self.store.add_source_event(
            event_id=f"evt-user-{self._next()}",
            topic=self.topic,
            project_name=PROJECT,
            created_at=self.clock() + self._seq,
            payload={"oldValue": old, "newValue": new},
            summary={"entityId": self.entity_id},
            user=user,
        )

    def inbound_pull(self, *_args: Any, **_kwargs: Any) -> None:
        """Simulate the addon applying the current Kitsu state."""
        change = self._apply_inbound()
        if change is None:
            return None
        self.ayon_writes += 1
        old, new = change
        marked = sync_event(
            id=f"evt-sync-{self._next()}",
            topic=self.topic,
            project=PROJECT,
            createdAt=self.clock() + self._seq,
            user=None,
            sender="kitsu-server-addon",
            summary={"entityId": self.entity_id},
            payload={"oldValue": old, "newValue": new},
        )
        self.store.add_source_event(
            event_id=marked["id"],
            topic=marked["topic"],
            project_name=PROJECT,
            created_at=marked["createdAt"],
            payload=marked["payload"],
            summary=marked["summary"],
            user=None,
            sender=marked["sender"],
            sender_type=marked["sender_type"],
        )
        return None

    def run_until_quiescent(self, max_steps: int = 50) -> int:
        """Poll the runner, echoing each Kitsu write back inbound."""
        steps = 0
        while self.runner.poll_once():
            steps += 1
            assert steps <= max_steps, "echo did not settle"
            marker = self._kitsu_marker()
            if marker > self._marker:
                self._marker = marker
                self.kitsu_writes += 1
                self.inbound_pull()
        return steps

    def _next(self) -> int:
        self._seq += 1
        return self._seq


class StatusEchoRig(EchoRig):
    """Task status echo."""

    topic = TOPIC_TASK_STATUS_CHANGED
    enable = ("task_status",)
    disable = ()

    def __init__(
        self,
        statuses: List[Dict[str, Any]],
        ayon_status: str,
        kitsu_status: str,
        policy: str = "kitsu_wins",
    ) -> None:
        self._init = (statuses, ayon_status, kitsu_status)
        super().__init__(policy)

    def setup(self) -> None:
        statuses, ayon_status, kitsu_status = self._init
        self.writer.statuses = [dict(s) for s in statuses]
        kitsu_id = next(
            s["id"] for s in statuses if s["name"] == kitsu_status
        )
        self.store.entities[("task", TASK_ID)] = {
            "id": TASK_ID,
            "name": "animation",
            "status": ayon_status,
            "data": {"kitsuId": KITSU_ID},
        }
        self.writer.tasks[KITSU_ID] = {
            "id": KITSU_ID,
            "project_id": KITSU_PROJECT,
            "task_status_id": kitsu_id,
        }

    def _kitsu_marker(self) -> int:
        return len(self.writer.comments)

    def user_changes_status(self, new_status: str, user: str = "bob"):
        """Change the AYON status as a user."""
        old = self.ayon_state["status"]
        if old == new_status:
            return False
        self.ayon_state["status"] = new_status
        self.emit_user_event(old, new_status, user)
        return True

    def _apply_inbound(self) -> Optional[Tuple[Any, Any]]:
        current = self.kitsu_state["task_status_id"]
        status = next(
            s for s in self.writer.statuses if s["id"] == current
        )
        wanted = kitsu_status_to_ayon(status)
        old = self.ayon_state["status"]
        if old == wanted:
            return None
        self.ayon_state["status"] = wanted
        return old, wanted


class AssigneeEchoRig(EchoRig):
    """Task assignee echo."""

    topic = TOPIC_TASK_ASSIGNEES_CHANGED
    enable = ("task_assignees",)

    def __init__(
        self,
        ayon_users: List[Dict[str, Any]],
        kitsu_persons: List[Dict[str, Any]],
        ayon_assignees: List[str],
        kitsu_assignee_ids: List[str],
        policy: str = "kitsu_wins",
    ) -> None:
        self._init = (
            ayon_users,
            kitsu_persons,
            ayon_assignees,
            kitsu_assignee_ids,
        )
        super().__init__(policy)

    def setup(self) -> None:
        users, persons, ayon_assignees, kitsu_ids = self._init
        self.store.users = [dict(u) for u in users]
        self.writer.persons = [dict(p) for p in persons]
        self.store.entities[("task", TASK_ID)] = {
            "id": TASK_ID,
            "name": "lighting",
            "assignees": list(ayon_assignees),
            "data": {"kitsuId": KITSU_ID},
        }
        self.writer.tasks[KITSU_ID] = {
            "id": KITSU_ID,
            "project_id": KITSU_PROJECT,
            "assignees": sorted(kitsu_ids),
        }

    def _kitsu_marker(self) -> int:
        return len(self.writer.assigned) + len(self.writer.unassigned)

    def user_changes_assignees(
        self, new: List[str], user: str = "coordinator"
    ) -> bool:
        """Change the AYON assignees as a user."""
        old = list(self.ayon_state["assignees"])
        if sorted(old) == sorted(new):
            return False
        self.ayon_state["assignees"] = list(new)
        self.emit_user_event(old, list(new), user)
        return True

    def _apply_inbound(self) -> Optional[Tuple[Any, Any]]:
        email_by_id = {
            p["id"]: p["email"]
            for p in self.writer.persons
            if p.get("id") and p.get("email")
        }
        emails = [
            email_by_id[pid]
            for pid in self.kitsu_state.get("assignees", [])
            if pid in email_by_id
        ]
        wanted = match_assignees_by_email(emails, self.store.users)
        old = list(self.ayon_state["assignees"])
        if old == list(wanted):
            return None
        self.ayon_state["assignees"] = list(wanted)
        return old, list(wanted)


class AttribEchoRig(EchoRig):
    """Folder attribute echo."""

    topic = TOPIC_FOLDER_ATTRIB_CHANGED
    entity_kind = "folder"
    entity_id = FOLDER_ID
    enable = ("entity_attributes",)

    def __init__(
        self,
        ayon_attribs: Dict[str, Any],
        kitsu_entity: Dict[str, Any],
        policy: str = "kitsu_wins",
    ) -> None:
        self._init = (ayon_attribs, kitsu_entity)
        super().__init__(policy)

    def setup(self) -> None:
        attribs, kitsu_entity = self._init
        self.store.entities[("folder", FOLDER_ID)] = {
            "id": FOLDER_ID,
            "name": "sh010",
            "attrib": dict(attribs),
            "ownAttrib": list(attribs),
            "data": {"kitsuId": KITSU_ID},
        }
        entity = {
            "id": KITSU_ID,
            "type": "Shot",
            "project_id": KITSU_PROJECT,
        }
        entity.update(kitsu_entity)
        entity["data"] = dict(kitsu_entity.get("data") or {})
        self.writer.tasks[KITSU_ID] = entity

    def _kitsu_marker(self) -> int:
        return len(self.writer.updated_fields)

    def user_changes_attribs(
        self, new: Dict[str, Any], user: str = "pipeline_td"
    ) -> bool:
        """Change AYON attributes as a user; emit the diff event."""
        attrib = self.ayon_state["attrib"]
        own = self.ayon_state["ownAttrib"]
        old_diff: Dict[str, Any] = {}
        new_diff: Dict[str, Any] = {}
        for key, value in new.items():
            if attrib.get(key) != value:
                old_diff[key] = attrib.get(key)
                new_diff[key] = value
                attrib[key] = value
                if key not in own:
                    own.append(key)
        if not new_diff:
            return False
        self.emit_user_event(old_diff, new_diff, user)
        return True

    def _apply_inbound(self) -> Optional[Tuple[Any, Any]]:
        view = kitsu_attrib_view(self.kitsu_state)
        attrib = self.ayon_state["attrib"]
        old_diff: Dict[str, Any] = {}
        new_diff: Dict[str, Any] = {}
        for key, value in view.items():
            if attrib.get(key) != value:
                old_diff[key] = attrib.get(key)
                new_diff[key] = value
                attrib[key] = value
        if not new_diff:
            return None
        return old_diff, new_diff

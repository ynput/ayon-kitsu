"""Deterministic echo simulator for two-way sync (Slices 1 and 2).

Validates: Requirements 5.3, 5.5, 5.12, 7.5
"""

from __future__ import annotations

import collections
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from processor.outbound.conflict import decide_field
from processor.outbound.constants import (
    ORIGIN_MARKERS,
    TOPIC_FOLDER_ATTRIB_CHANGED,
    TOPIC_TASK_ASSIGNEES_CHANGED,
    TOPIC_TASK_ATTRIB_CHANGED,
    TOPIC_TASK_STATUS_CHANGED,
)
from processor.outbound.gating import gate_decision
from processor.outbound.inbound_mirror import match_assignees_by_email
from processor.outbound.loop_guard import loop_guard_apply
from processor.outbound.mapping import (
    _extract_user_email,
    _extract_user_kitsu_id,
    kitsu_attrib_view,
    kitsu_person_owner,
    kitsu_status_to_ayon,
    map_status,
    resolve_assignees,
)
from processor.outbound.origin import classify_origin
from processor.outbound.planning import (
    merge_kitsu_data,
    plan_assignee_update,
    plan_attribute_write,
)

try:
    from server.kitsu.constants import sync_event
except ImportError:
    try:
        from constants import sync_event  # type: ignore
    except ImportError:
        def sync_event(**event: Any) -> Dict[str, Any]:
            marked = dict(event)
            summary = dict(marked.get("summary") or {})
            summary["kitsuSyncOrigin"] = True
            marked["summary"] = summary
            marked["sender_type"] = "kitsu_sync"
            return marked


def check_user_roundtrip_condition(
    user: Dict[str, Any],
    ayon_users: List[Dict[str, Any]],
    kitsu_persons: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Check whether an AYON user satisfies Requirement 7.5 round-trip.

    Conditions from Requirement 7.5:
    1. Email is non-empty string.
    2. Email is unique among AYON users.
    3. Email matches exactly one Kitsu person.
    4. Kitsu_Id is absent or references that same Kitsu person.

    Returns:
        Tuple of (satisfies, reason_if_not).
    """
    if not isinstance(user, dict):
        return False, "invalid_user_dict"

    email = _extract_user_email(user)
    if not email:
        return False, "empty_email"

    matching_ayon = [
        u
        for u in ayon_users
        if isinstance(u, dict) and _extract_user_email(u) == email
    ]
    if len(matching_ayon) != 1:
        return False, f"ayon_email_match_count_{len(matching_ayon)}"

    matching_kitsu = [
        p
        for p in kitsu_persons
        if isinstance(p, dict) and p.get("email") == email
    ]
    if len(matching_kitsu) != 1:
        return False, f"kitsu_email_match_count_{len(matching_kitsu)}"

    kitsu_person = matching_kitsu[0]
    user_kitsu_id = _extract_user_kitsu_id(user)
    if user_kitsu_id is not None and user_kitsu_id != kitsu_person.get("id"):
        return False, "mismatched_kitsu_id"

    return True, "ok"


def count_users_outside_roundtrip_conditions(
    ayon_users: List[Dict[str, Any]],
    kitsu_persons: List[Dict[str, Any]],
) -> int:
    """Count AYON users falling outside Requirement 7.5 round-trip rules."""
    count = 0
    for u in ayon_users:
        ok, _ = check_user_roundtrip_condition(u, ayon_users, kitsu_persons)
        if not ok:
            count += 1
    return count


def make_default_toggles(
    task_status: bool = True,
    task_assignees: bool = False,
    entity_attributes: bool = False,
    conflict_policy: str = "kitsu_wins",
) -> Dict[str, Any]:
    """Create a valid EffectiveToggles dict with specified categories."""
    return {
        "valid": True,
        "error": None,
        "master": True,
        "categories": {
            "task_status": task_status,
            "task_assignees": task_assignees,
            "entity_attributes": entity_attributes,
            "entity_creation": False,
            "entity_rename": False,
            "entity_deletion": False,
        },
        "conflict_policy": conflict_policy,
    }


def make_gate_snapshot(toggles: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap effective toggles in a gate snapshot structure."""
    return {
        "state": "snapshot",
        "toggles": toggles,
    }


class EchoSimulator:
    """Deterministic simulation harness for AYON <-> Kitsu sync."""

    def __init__(
        self,
        ayon_task: Optional[Dict[str, Any]] = None,
        kitsu_task: Optional[Dict[str, Any]] = None,
        kitsu_statuses: Optional[List[Dict[str, Any]]] = None,
        toggles_now: Optional[Dict[str, Any]] = None,
        toggles_at_creation: Optional[Dict[str, Any]] = None,
        conflict_policy: str = "kitsu_wins",
        sim_time: float = 1000.0,
        *,
        ayon_users: Optional[List[Dict[str, Any]]] = None,
        kitsu_persons: Optional[List[Dict[str, Any]]] = None,
        ayon_entity: Optional[Dict[str, Any]] = None,
        kitsu_entity: Optional[Dict[str, Any]] = None,
        entity_type: str = "task",
    ) -> None:
        """Initialize the simulator with entity state and configuration."""
        if ayon_entity is not None:
            self.ayon_state = dict(ayon_entity)
        elif ayon_task is not None:
            self.ayon_state = dict(ayon_task)
        else:
            self.ayon_state = {}

        if kitsu_entity is not None:
            self.kitsu_state = dict(kitsu_entity)
        elif kitsu_task is not None:
            self.kitsu_state = dict(kitsu_task)
        else:
            self.kitsu_state = {}

        self.entity_type = entity_type
        self.kitsu_statuses = (
            [dict(s) for s in kitsu_statuses] if kitsu_statuses else []
        )
        self.ayon_users = [dict(u) for u in (ayon_users or [])]
        self.kitsu_persons = [dict(p) for p in (kitsu_persons or [])]

        if toggles_now is None:
            toggles_now = make_default_toggles()
        toggles_now["conflict_policy"] = conflict_policy
        self.toggles_now = toggles_now

        if toggles_at_creation is None:
            toggles_at_creation = make_gate_snapshot(self.toggles_now)
        self.toggles_at_creation = toggles_at_creation

        self.sim_time = float(sim_time)
        self.loop_guard_state: Dict[Tuple[str, str], Any] = {}
        self.loop_guard_fired = False

        self.write_counters: Dict[str, Dict[str, int]] = {
            "kitsu": {
                "task_status": 0,
                "task_status_id": 0,
                "task_assignees": 0,
                "assignees": 0,
                "entity_attributes": 0,
                "attributes": 0,
            },
            "ayon": {
                "task_status": 0,
                "status": 0,
                "task_assignees": 0,
                "assignees": 0,
                "entity_attributes": 0,
                "attrib": 0,
            },
        }

        self.unmet_conditions: List[Dict[str, Any]] = []
        self.event_queue: collections.deque[Dict[str, Any]] = (
            collections.deque()
        )
        self.event_trace: List[Dict[str, Any]] = []
        self.ayon_write_events: List[Dict[str, Any]] = []

        # Category plug-in registries
        self._outbound_handlers: Dict[str, Callable[..., Any]] = {
            "task_status": self._handle_outbound_task_status,
            "task_assignees": self._handle_outbound_task_assignees,
            "entity_attributes": self._handle_outbound_entity_attributes,
        }
        self._inbound_handlers: Dict[str, Callable[..., Any]] = {
            "task_status": self._handle_inbound_task_status,
            "task_assignees": self._handle_inbound_task_assignees,
            "entity_attributes": self._handle_inbound_entity_attributes,
        }

    @property
    def kitsu_writes(self) -> Dict[str, int]:
        """Convenience property for Kitsu write counts."""
        return self.write_counters["kitsu"]

    @property
    def ayon_writes(self) -> Dict[str, int]:
        """Convenience property for AYON write counts."""
        return self.write_counters["ayon"]

    def apply_user_ayon_status_change(
        self,
        new_status: str,
        user: Optional[str] = "alice",
        sender: Optional[str] = None,
    ) -> bool:
        """Apply a user change in AYON status and enqueue event."""
        old_status = self.ayon_state.get("status")
        if old_status == new_status:
            return False

        self.ayon_state["status"] = new_status
        event = {
            "id": f"evt-{uuid.uuid4()}",
            "topic": TOPIC_TASK_STATUS_CHANGED,
            "project": self.ayon_state.get("project", "test_project"),
            "createdAt": self.sim_time,
            "user": user,
            "sender": sender,
            "senderType": None,
            "summary": {"entityId": self.ayon_state.get("id", "task-1")},
            "payload": {
                "oldValue": old_status,
                "newValue": new_status,
            },
        }
        self.event_queue.append(event)
        return True

    def apply_user_ayon_assignee_change(
        self,
        new_assignees: List[str],
        user: Optional[str] = "coordinator",
        sender: Optional[str] = None,
    ) -> bool:
        """Apply a user change in AYON task assignees and enqueue event."""
        old_assignees = list(self.ayon_state.get("assignees", []))
        if sorted(old_assignees) == sorted(new_assignees):
            return False

        self.ayon_state["assignees"] = list(new_assignees)
        event = {
            "id": f"evt-{uuid.uuid4()}",
            "topic": TOPIC_TASK_ASSIGNEES_CHANGED,
            "project": self.ayon_state.get("project", "test_project"),
            "createdAt": self.sim_time,
            "user": user,
            "sender": sender,
            "senderType": None,
            "summary": {"entityId": self.ayon_state.get("id", "task-1")},
            "payload": {
                "oldValue": old_assignees,
                "newValue": list(new_assignees),
            },
        }
        self.event_queue.append(event)
        return True

    def apply_user_ayon_attrib_change(
        self,
        new_attribs: Dict[str, Any],
        user: Optional[str] = "pipeline_td",
        sender: Optional[str] = None,
    ) -> bool:
        """Apply a user change in AYON entity attributes and enqueue event."""
        curr_attrib = self.ayon_state.setdefault("attrib", {})
        own_attrib = self.ayon_state.setdefault("own_attrib", [])
        old_diff = {}
        new_diff = {}

        for k, v in new_attribs.items():
            if curr_attrib.get(k) != v:
                old_diff[k] = curr_attrib.get(k)
                new_diff[k] = v
                curr_attrib[k] = v
                if k not in own_attrib:
                    own_attrib.append(k)

        if not new_diff:
            return False

        topic = (
            TOPIC_TASK_ATTRIB_CHANGED
            if self.entity_type == "task"
            else TOPIC_FOLDER_ATTRIB_CHANGED
        )
        event = {
            "id": f"evt-{uuid.uuid4()}",
            "topic": topic,
            "project": self.ayon_state.get("project", "test_project"),
            "createdAt": self.sim_time,
            "user": user,
            "sender": sender,
            "senderType": None,
            "summary": {"entityId": self.ayon_state.get("id", "entity-1")},
            "payload": {
                "oldValue": old_diff,
                "newValue": new_diff,
            },
        }
        self.event_queue.append(event)
        return True

    def advance_time(self, seconds: float) -> None:
        """Advance simulated time by a number of seconds."""
        self.sim_time += float(seconds)

    def step(self) -> Optional[Dict[str, Any]]:
        """Process one pending event from the queue."""
        if not self.event_queue:
            return None

        event = self.event_queue.popleft()
        event_type = event.get("type", "ayon")

        kitsu_before = dict(self.kitsu_writes)

        if event_type == "kitsu":
            res = self._process_kitsu_event(event)
        else:
            res = self._process_ayon_event(event)

        kitsu_after = dict(self.kitsu_writes)
        res["kitsu_writes_before"] = kitsu_before
        res["kitsu_writes_after"] = kitsu_after

        self.event_trace.append(res)
        return res

    def run_until_quiescent(self, max_steps: int = 50) -> int:
        """Run the simulation until no pending events remain."""
        steps = 0
        while self.event_queue:
            if steps >= max_steps:
                raise RuntimeError(
                    f"Simulation not quiescent within {max_steps} "
                    f"steps (pending: {len(self.event_queue)})"
                )
            self.step()
            steps += 1
        return steps

    def _process_ayon_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process an AYON event outbound."""
        origin = classify_origin(event, ORIGIN_MARKERS)
        if origin in ("sync_originated", "origin_unknown"):
            return {
                "direction": "outbound",
                "decision": "skipped",
                "reason": f"origin {origin}",
                "event": event,
            }

        topic = event.get("topic", "")
        if topic == TOPIC_TASK_STATUS_CHANGED:
            handler = self._outbound_handlers.get("task_status")
            if handler is not None:
                return handler(event)

        if topic == TOPIC_TASK_ASSIGNEES_CHANGED:
            handler = self._outbound_handlers.get("task_assignees")
            if handler is not None:
                return handler(event)

        if topic in (TOPIC_FOLDER_ATTRIB_CHANGED, TOPIC_TASK_ATTRIB_CHANGED):
            handler = self._outbound_handlers.get("entity_attributes")
            if handler is not None:
                return handler(event)

        return {
            "direction": "outbound",
            "decision": "skipped",
            "reason": f"unhandled topic {topic}",
            "event": event,
        }

    def _handle_outbound_task_status(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle outbound task status synchronization."""
        g_dec = gate_decision(
            "task_status",
            self.toggles_at_creation,
            self.toggles_now,
        )
        if not g_dec.get("allowed"):
            return {
                "direction": "outbound",
                "category": "task_status",
                "decision": "skipped",
                "reason": g_dec.get("reason"),
                "event": event,
            }

        payload = event.get("payload") or {}
        new_val = payload.get("newValue")
        entity_id = self.ayon_state.get("id", "")
        kitsu_id = self.kitsu_state.get("id", "")

        new_map = map_status(new_val, self.kitsu_statuses)
        if not new_map.get("ok"):
            err_kind = new_map.get("error", "unmatched")
            cnt = new_map.get("count", 0)
            self.unmet_conditions.append({
                "category": "task_status",
                "field": "task_status_id",
                "condition": err_kind,
                "name": new_val,
                "match_count": cnt,
            })
            return {
                "direction": "outbound",
                "category": "task_status",
                "decision": "failed",
                "reason": f"status {new_val} {err_kind}",
                "event": event,
            }

        target_status_id = new_map["status"]["id"]

        old_val = payload.get("oldValue")
        has_prev = old_val is not None
        prev_id = None
        if has_prev:
            prev_map = map_status(old_val, self.kitsu_statuses)
            if prev_map.get("ok"):
                prev_id = prev_map["status"]["id"]
            else:
                has_prev = False

        current_kitsu_status_id = self.kitsu_state.get("task_status_id")
        policy = self.toggles_now.get("conflict_policy", "kitsu_wins")
        f_dec = decide_field(
            "task_status_id",
            prev_id,
            current_kitsu_status_id,
            target_status_id,
            has_previous=has_prev,
            policy=policy,
        )

        action = f_dec.get("action")
        if action == "skip_in_sync":
            return {
                "direction": "outbound",
                "category": "task_status",
                "decision": "skipped_in_sync",
                "event": event,
            }

        if action == "conflict_keep_kitsu":
            self._pull_kitsu_status_inbound()
            return {
                "direction": "outbound",
                "category": "task_status",
                "decision": "conflict_keep_kitsu",
                "event": event,
            }

        lg_res, new_guard_state = loop_guard_apply(
            self.loop_guard_state,
            entity_id,
            "task_status_id",
            self.sim_time,
        )
        if not lg_res.get("allowed"):
            self.loop_guard_fired = True
            self.loop_guard_state = new_guard_state
            return {
                "direction": "outbound",
                "category": "task_status",
                "decision": "skipped",
                "reason": "loop suspected",
                "event": event,
            }

        self.loop_guard_state = new_guard_state
        self.write_counters["kitsu"]["task_status"] += 1
        self.write_counters["kitsu"]["task_status_id"] += 1
        self.kitsu_state["task_status_id"] = target_status_id

        self.event_queue.append({
            "type": "kitsu",
            "event": "task:update",
            "task_id": kitsu_id,
            "category": "task_status",
            "project_id": self.kitsu_state.get("project_id", ""),
            "createdAt": self.sim_time,
        })

        return {
            "direction": "outbound",
            "category": "task_status",
            "decision": "applied",
            "written_value": target_status_id,
            "event": event,
        }

    def _pull_kitsu_status_inbound(self) -> None:
        """Pull current Kitsu status to AYON during conflict_keep_kitsu."""
        curr_id = self.kitsu_state.get("task_status_id")
        status_obj = next(
            (s for s in self.kitsu_statuses if s.get("id") == curr_id),
            None,
        )
        if status_obj is None:
            self.unmet_conditions.append({
                "category": "task_status",
                "field": "task_status_id",
                "condition": "kitsu_status_not_found",
                "status_id": curr_id,
            })
            return

        ayon_name = kitsu_status_to_ayon(status_obj)
        old_val = self.ayon_state.get("status")
        if old_val != ayon_name:
            self.ayon_state["status"] = ayon_name
            self.write_counters["ayon"]["task_status"] += 1
            self.write_counters["ayon"]["status"] += 1
            evt = sync_event(
                id=f"evt-{uuid.uuid4()}",
                topic=TOPIC_TASK_STATUS_CHANGED,
                project=self.ayon_state.get("project", "test_project"),
                createdAt=self.sim_time,
                user=None,
                sender="kitsu-processor",
                summary={"entityId": self.ayon_state.get("id", "")},
                payload={"oldValue": old_val, "newValue": ayon_name},
            )
            self.ayon_write_events.append({
                "category": "task_status",
                "written_value": ayon_name,
                "event": evt,
            })
            self.event_queue.append(evt)

    def _handle_outbound_task_assignees(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle outbound task assignees synchronization."""
        g_dec = gate_decision(
            "task_assignees",
            self.toggles_at_creation,
            self.toggles_now,
        )
        if not g_dec.get("allowed"):
            return {
                "direction": "outbound",
                "category": "task_assignees",
                "decision": "skipped",
                "reason": g_dec.get("reason"),
                "event": event,
            }

        payload = event.get("payload") or {}
        new_val = payload.get("newValue") or []
        old_val = payload.get("oldValue")
        entity_id = self.ayon_state.get("id", "")
        kitsu_id = self.kitsu_state.get("id", "")

        res = resolve_assignees(new_val, self.ayon_users, self.kitsu_persons)
        if res.get("unresolved"):
            for u_name, reason in res["unresolved"].items():
                self.unmet_conditions.append({
                    "category": "task_assignees",
                    "field": "assignees",
                    "condition": reason,
                    "username": u_name,
                })

        for u_name in new_val:
            u_obj = next(
                (
                    u
                    for u in self.ayon_users
                    if isinstance(u, dict) and u.get("name") == u_name
                ),
                None,
            )
            if u_obj is not None:
                ok, reason = check_user_roundtrip_condition(
                    u_obj, self.ayon_users, self.kitsu_persons
                )
                if not ok:
                    if not any(
                        d.get("category") == "task_assignees"
                        and d.get("username") == u_name
                        for d in self.unmet_conditions
                    ):
                        self.unmet_conditions.append({
                            "category": "task_assignees",
                            "field": "assignees",
                            "condition": reason,
                            "username": u_name,
                        })

        resolved_ids = list(res.get("resolved", {}).values())

        managed_ids = [
            p["id"]
            for p in self.kitsu_persons
            if kitsu_person_owner(p, self.ayon_users) is not None
        ]

        cur_ids = [str(pid) for pid in self.kitsu_state.get("assignees", [])]
        cur_set = set(cur_ids)
        managed_cur_ids = sorted(cur_set & set(managed_ids))

        policy = self.toggles_now.get("conflict_policy", "kitsu_wins")
        has_prev = old_val is not None
        if has_prev:
            old_res = resolve_assignees(
                old_val, self.ayon_users, self.kitsu_persons
            )
            old_resolved_ids = sorted(
                set(old_res.get("resolved", {}).values())
            )
            if old_resolved_ids != managed_cur_ids:
                if policy == "kitsu_wins":
                    self._pull_kitsu_assignees_inbound()
                    return {
                        "direction": "outbound",
                        "category": "task_assignees",
                        "decision": "conflict_keep_kitsu",
                        "event": event,
                    }

        plan = plan_assignee_update(cur_ids, resolved_ids, managed_ids)
        if not plan.get("add") and not plan.get("remove"):
            return {
                "direction": "outbound",
                "category": "task_assignees",
                "decision": "skipped_in_sync",
                "event": event,
            }

        lg_res, new_guard_state = loop_guard_apply(
            self.loop_guard_state,
            entity_id,
            "assignees",
            self.sim_time,
        )
        if not lg_res.get("allowed"):
            self.loop_guard_fired = True
            self.loop_guard_state = new_guard_state
            return {
                "direction": "outbound",
                "category": "task_assignees",
                "decision": "skipped",
                "reason": "loop suspected",
                "event": event,
            }

        self.loop_guard_state = new_guard_state
        self.write_counters["kitsu"]["task_assignees"] += 1
        self.write_counters["kitsu"]["assignees"] += 1

        new_kitsu_set = (
            (cur_set | set(plan.get("add", [])))
            - set(plan.get("remove", []))
        )
        remaining_unmanaged = [
            pid
            for pid in cur_ids
            if pid not in managed_ids and pid not in plan.get("remove", [])
        ]
        new_kitsu_list = [
            pid for pid in resolved_ids if pid in new_kitsu_set
        ] + [
            pid
            for pid in plan.get("add", [])
            if pid not in resolved_ids and pid in new_kitsu_set
        ] + remaining_unmanaged
        self.kitsu_state["assignees"] = new_kitsu_list

        self.event_queue.append({
            "type": "kitsu",
            "event": "task:update",
            "task_id": kitsu_id,
            "category": "task_assignees",
            "createdAt": self.sim_time,
        })

        return {
            "direction": "outbound",
            "category": "task_assignees",
            "decision": "applied",
            "written_value": list(new_kitsu_list),
            "event": event,
        }

    def _pull_kitsu_assignees_inbound(self) -> None:
        """Pull current Kitsu task assignees to AYON on conflict."""
        cur_ids = self.kitsu_state.get("assignees", [])
        id_to_email = {
            p["id"]: p["email"]
            for p in self.kitsu_persons
            if isinstance(p, dict) and p.get("id") and p.get("email")
        }
        emails = [
            id_to_email[pid]
            for pid in cur_ids
            if pid in id_to_email
        ]
        desired_users = match_assignees_by_email(emails, self.ayon_users)
        old_val = self.ayon_state.get("assignees", [])
        if list(old_val) != list(desired_users):
            self.ayon_state["assignees"] = list(desired_users)
            self.write_counters["ayon"]["task_assignees"] += 1
            self.write_counters["ayon"]["assignees"] += 1
            evt = sync_event(
                id=f"evt-{uuid.uuid4()}",
                topic=TOPIC_TASK_ASSIGNEES_CHANGED,
                project=self.ayon_state.get("project", "test_project"),
                createdAt=self.sim_time,
                user=None,
                sender="kitsu-processor",
                summary={"entityId": self.ayon_state.get("id", "")},
                payload={"oldValue": old_val, "newValue": list(desired_users)},
            )
            self.ayon_write_events.append({
                "category": "task_assignees",
                "written_value": list(desired_users),
                "event": evt,
            })
            self.event_queue.append(evt)

    def _handle_outbound_entity_attributes(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle outbound entity attributes synchronization."""
        g_dec = gate_decision(
            "entity_attributes",
            self.toggles_at_creation,
            self.toggles_now,
        )
        if not g_dec.get("allowed"):
            return {
                "direction": "outbound",
                "category": "entity_attributes",
                "decision": "skipped",
                "reason": g_dec.get("reason"),
                "event": event,
            }

        payload = event.get("payload") or {}
        new_values = payload.get("newValue") or {}
        old_values = payload.get("oldValue") or {}
        entity_id = self.ayon_state.get("id", "")
        kitsu_id = self.kitsu_state.get("id", "")

        effective_attrib = dict(self.ayon_state.get("attrib") or {})
        own_attrib = list(self.ayon_state.get("own_attrib") or [])

        plan = plan_attribute_write(new_values, effective_attrib, own_attrib)
        if plan.get("errors"):
            for err in plan["errors"]:
                self.unmet_conditions.append({
                    "category": "entity_attributes",
                    "field": "frame_range",
                    "condition": "invalid_frame_range",
                    "error": err,
                })

        planned_fields = plan.get("fields") or {}
        if not planned_fields:
            return {
                "direction": "outbound",
                "category": "entity_attributes",
                "decision": "failed" if plan.get("errors") else "skipped",
                "reason": (
                    "invalid frame range"
                    if plan.get("errors")
                    else "no mapped fields"
                ),
                "event": event,
            }

        policy = self.toggles_now.get("conflict_policy", "kitsu_wins")
        kitsu_view = kitsu_attrib_view(self.kitsu_state)

        conflicts = set()
        decisions = {}
        for attr_name in (
            "fps",
            "description",
            "resolutionWidth",
            "resolutionHeight",
            "frameStart",
            "frameEnd",
        ):
            if attr_name not in new_values:
                continue
            has_prev = attr_name in old_values
            prev_v = old_values.get(attr_name)
            curr_kitsu_v = kitsu_view.get(attr_name)
            target_v = effective_attrib.get(attr_name)
            f_dec = decide_field(
                attr_name,
                prev_v,
                curr_kitsu_v,
                target_v,
                has_previous=has_prev,
                policy=policy,
            )
            decisions[attr_name] = f_dec
            if f_dec.get("action") == "conflict_keep_kitsu":
                conflicts.add(attr_name)

        fields_to_write = {}
        fps_dec = decisions.get("fps")
        if fps_dec and fps_dec.get("action") in (
            "write", "write_no_previous", "conflict_overwrite"
        ):
            if "data.fps" in planned_fields:
                fields_to_write["data.fps"] = planned_fields["data.fps"]

        desc_dec = decisions.get("description")
        if desc_dec and desc_dec.get("action") in (
            "write", "write_no_previous", "conflict_overwrite"
        ):
            if "description" in planned_fields:
                fields_to_write["description"] = (
                    planned_fields["description"]
                )

        target_res = planned_fields.get("data.resolution")
        has_res_conflict = bool(
            {"resolutionWidth", "resolutionHeight"} & conflicts
        )
        if target_res is not None and not has_res_conflict:
            curr_w = kitsu_view.get("resolutionWidth")
            curr_h = kitsu_view.get("resolutionHeight")
            curr_res = f"{curr_w}x{curr_h}" if curr_w and curr_h else None
            if target_res != curr_res:
                fields_to_write["data.resolution"] = target_res

        target_in = planned_fields.get("data.frame_in")
        target_out = planned_fields.get("data.frame_out")
        has_frame_conflict = bool(
            {"frameStart", "frameEnd"} & conflicts
        )
        if not has_frame_conflict:
            curr_in = kitsu_view.get("frameStart")
            curr_out = kitsu_view.get("frameEnd")
            if target_in != curr_in or target_out != curr_out:
                if target_in is not None:
                    fields_to_write["data.frame_in"] = target_in
                if target_out is not None:
                    fields_to_write["data.frame_out"] = target_out
                if "nb_frames" in planned_fields:
                    fields_to_write["nb_frames"] = (
                        planned_fields["nb_frames"]
                    )

        has_kitsu_conflict = bool(conflicts and policy == "kitsu_wins")
        if has_kitsu_conflict:
            self._pull_kitsu_attributes_inbound(conflicts)

        if not fields_to_write:
            if has_kitsu_conflict:
                return {
                    "direction": "outbound",
                    "category": "entity_attributes",
                    "decision": "conflict_keep_kitsu",
                    "written_fields": {},
                    "event": event,
                }
            return {
                "direction": "outbound",
                "category": "entity_attributes",
                "decision": "skipped_in_sync",
                "event": event,
            }

        lg_res, new_guard_state = loop_guard_apply(
            self.loop_guard_state,
            entity_id,
            "entity_attributes",
            self.sim_time,
        )
        if not lg_res.get("allowed"):
            self.loop_guard_fired = True
            self.loop_guard_state = new_guard_state
            return {
                "direction": "outbound",
                "category": "entity_attributes",
                "decision": "skipped",
                "reason": "loop suspected",
                "event": event,
            }

        self.loop_guard_state = new_guard_state
        self.write_counters["kitsu"]["entity_attributes"] += 1
        self.write_counters["kitsu"]["attributes"] += 1

        cur_data = self.kitsu_state.get("data") or {}
        merged_data = merge_kitsu_data(cur_data, fields_to_write)
        self.kitsu_state["data"] = merged_data

        if "nb_frames" in fields_to_write:
            self.kitsu_state["nb_frames"] = fields_to_write["nb_frames"]
        if "description" in fields_to_write:
            self.kitsu_state["description"] = fields_to_write["description"]

        self.event_queue.append({
            "type": "kitsu",
            "event": "entity:update",
            "entity_id": kitsu_id,
            "category": "entity_attributes",
            "createdAt": self.sim_time,
        })

        decision = "conflict_keep_kitsu" if has_kitsu_conflict else "applied"
        return {
            "direction": "outbound",
            "category": "entity_attributes",
            "decision": decision,
            "written_fields": fields_to_write,
            "event": event,
        }

    def _pull_kitsu_attributes_inbound(
        self,
        conflicts: Optional[Set[str]] = None,
    ) -> None:
        """Pull current Kitsu attributes to AYON on conflict."""
        kitsu_view = kitsu_attrib_view(self.kitsu_state)
        curr_attrib = self.ayon_state.setdefault("attrib", {})
        old_diff = {}
        new_diff = {}
        changed = False
        target_keys = (
            conflicts if conflicts is not None else set(kitsu_view.keys())
        )
        for k in target_keys:
            if k in kitsu_view and curr_attrib.get(k) != kitsu_view[k]:
                old_diff[k] = curr_attrib.get(k)
                new_diff[k] = kitsu_view[k]
                curr_attrib[k] = kitsu_view[k]
                changed = True
        if changed:
            self.write_counters["ayon"]["entity_attributes"] += 1
            self.write_counters["ayon"]["attrib"] += 1
            topic = (
                TOPIC_TASK_ATTRIB_CHANGED
                if self.entity_type == "task"
                else TOPIC_FOLDER_ATTRIB_CHANGED
            )
            evt = sync_event(
                id=f"evt-{uuid.uuid4()}",
                topic=topic,
                project=self.ayon_state.get("project", "test_project"),
                createdAt=self.sim_time,
                user=None,
                sender="kitsu-processor",
                summary={"entityId": self.ayon_state.get("id", "")},
                payload={"oldValue": old_diff, "newValue": new_diff},
            )
            self.ayon_write_events.append({
                "category": "entity_attributes",
                "written_value": new_diff,
                "event": evt,
            })
            self.event_queue.append(evt)

    def _process_kitsu_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process a Kitsu event inbound."""
        category = event.get("category", "task_status")
        handler = self._inbound_handlers.get(category)
        if handler is not None:
            return handler(event)
        return {
            "direction": "inbound",
            "decision": "skipped",
            "reason": f"unhandled inbound event category {category}",
            "event": event,
        }

    def _handle_inbound_task_status(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle inbound task status processing (update_task equality)."""
        curr_id = self.kitsu_state.get("task_status_id")
        status_obj = next(
            (s for s in self.kitsu_statuses if s.get("id") == curr_id),
            None,
        )
        if status_obj is None:
            self.unmet_conditions.append({
                "category": "task_status",
                "field": "task_status_id",
                "condition": "kitsu_status_not_found",
                "status_id": curr_id,
            })
            return {
                "direction": "inbound",
                "category": "task_status",
                "decision": "failed",
                "reason": f"status id {curr_id} not found in Kitsu",
                "event": event,
            }

        desired_ayon_status = kitsu_status_to_ayon(status_obj)
        current_ayon_status = self.ayon_state.get("status")

        if desired_ayon_status == current_ayon_status:
            return {
                "direction": "inbound",
                "category": "task_status",
                "decision": "in_sync",
                "event": event,
            }

        self.ayon_state["status"] = desired_ayon_status
        self.write_counters["ayon"]["task_status"] += 1
        self.write_counters["ayon"]["status"] += 1

        marked_evt = sync_event(
            id=f"evt-{uuid.uuid4()}",
            topic=TOPIC_TASK_STATUS_CHANGED,
            project=self.ayon_state.get("project", "test_project"),
            createdAt=self.sim_time,
            user=None,
            sender="kitsu-server-addon",
            summary={"entityId": self.ayon_state.get("id", "")},
            payload={
                "oldValue": current_ayon_status,
                "newValue": desired_ayon_status,
            },
        )
        self.ayon_write_events.append({
            "category": "task_status",
            "written_value": desired_ayon_status,
            "event": marked_evt,
        })
        self.event_queue.append(marked_evt)

        return {
            "direction": "inbound",
            "category": "task_status",
            "decision": "updated",
            "written_value": desired_ayon_status,
            "event": event,
        }

    def _handle_inbound_task_assignees(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle inbound task assignees processing (update_task equality)."""
        cur_ids = self.kitsu_state.get("assignees", [])
        id_to_email = {
            p["id"]: p["email"]
            for p in self.kitsu_persons
            if isinstance(p, dict) and p.get("id") and p.get("email")
        }
        emails = [
            id_to_email[pid]
            for pid in cur_ids
            if pid in id_to_email
        ]
        desired_users = match_assignees_by_email(emails, self.ayon_users)
        curr_ayon = self.ayon_state.get("assignees", [])

        if list(curr_ayon) == list(desired_users):
            return {
                "direction": "inbound",
                "category": "task_assignees",
                "decision": "in_sync",
                "event": event,
            }

        self.ayon_state["assignees"] = list(desired_users)
        self.write_counters["ayon"]["task_assignees"] += 1
        self.write_counters["ayon"]["assignees"] += 1

        marked_evt = sync_event(
            id=f"evt-{uuid.uuid4()}",
            topic=TOPIC_TASK_ASSIGNEES_CHANGED,
            project=self.ayon_state.get("project", "test_project"),
            createdAt=self.sim_time,
            user=None,
            sender="kitsu-server-addon",
            summary={"entityId": self.ayon_state.get("id", "")},
            payload={
                "oldValue": curr_ayon,
                "newValue": list(desired_users),
            },
        )
        self.ayon_write_events.append({
            "category": "task_assignees",
            "written_value": list(desired_users),
            "event": marked_evt,
        })
        self.event_queue.append(marked_evt)

        return {
            "direction": "inbound",
            "category": "task_assignees",
            "decision": "updated",
            "written_value": list(desired_users),
            "event": event,
        }

    def _handle_inbound_entity_attributes(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle inbound entity attributes (update_folder/update_task)."""
        kitsu_view = kitsu_attrib_view(self.kitsu_state)
        curr_attrib = self.ayon_state.setdefault("attrib", {})
        old_diff = {}
        new_diff = {}
        changed = False

        for key, val in kitsu_view.items():
            if curr_attrib.get(key) != val:
                old_diff[key] = curr_attrib.get(key)
                new_diff[key] = val
                curr_attrib[key] = val
                changed = True

        if not changed:
            return {
                "direction": "inbound",
                "category": "entity_attributes",
                "decision": "in_sync",
                "event": event,
            }

        self.write_counters["ayon"]["entity_attributes"] += 1
        self.write_counters["ayon"]["attrib"] += 1

        topic = (
            TOPIC_TASK_ATTRIB_CHANGED
            if self.entity_type == "task"
            else TOPIC_FOLDER_ATTRIB_CHANGED
        )
        marked_evt = sync_event(
            id=f"evt-{uuid.uuid4()}",
            topic=topic,
            project=self.ayon_state.get("project", "test_project"),
            createdAt=self.sim_time,
            user=None,
            sender="kitsu-server-addon",
            summary={"entityId": self.ayon_state.get("id", "")},
            payload={
                "oldValue": old_diff,
                "newValue": new_diff,
            },
        )
        self.ayon_write_events.append({
            "category": "entity_attributes",
            "written_value": new_diff,
            "event": marked_evt,
        })
        self.event_queue.append(marked_evt)

        return {
            "direction": "inbound",
            "category": "entity_attributes",
            "decision": "updated",
            "written_value": new_diff,
            "event": event,
        }

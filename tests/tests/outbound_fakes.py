"""In-memory test doubles implementing F17 enroll semantics (Task 10.4).

Validates: Requirements 4.1, 4.2, 4.5, 4.9, 4.10, 4.11, 4.14, 10.1, 10.9.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from processor.outbound.kitsu_writer import KitsuWriterError


def _event_value(event: Dict[str, Any], key: str) -> Any:
    """Read an event field, treating sender_type and senderType alike."""
    if key in event:
        return event[key]
    aliases = {"sender_type": "senderType", "senderType": "sender_type"}
    alt = aliases.get(key)
    return event.get(alt) if alt else None


def evaluate_query_filter(
    query_filter: Optional[Dict[str, Any]], event: Dict[str, Any]
) -> bool:
    """Evaluate an AYON QueryFilter dict against an event dict.

    Args:
        query_filter: Filter with ``operator`` and ``conditions``, or None.
        event: Source event dict.

    Returns:
        True when the event matches (always True for a None filter).
    """
    if not query_filter:
        return True
    conditions = query_filter.get("conditions") or []
    if not conditions:
        return True
    results = []
    for cond in conditions:
        if "conditions" in cond:
            results.append(evaluate_query_filter(cond, event))
            continue
        op = str(cond.get("operator", "eq")).lower()
        val = _event_value(event, cond.get("key"))
        target = cond.get("value")
        if op == "eq":
            results.append(val == target)
        elif op == "ne":
            results.append(val != target)
        elif op == "in":
            results.append(val in (target or []))
        elif op == "notin":
            results.append(val not in (target or []))
        elif op == "isnull":
            results.append(val is None)
        elif op == "notnull":
            results.append(val is not None)
        else:
            raise ValueError(f"Unsupported operator: {op}")
    if str(query_filter.get("operator", "and")).lower() == "or":
        return any(results)
    return all(results)


class FakeClock:
    """Controllable clock for deterministic time testing."""

    def __init__(self, start: float = 1000.0):
        self.current_time = float(start)

    def __call__(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += float(seconds)


class FakeAyonStore:
    """In-memory event and entity store implementing F17 enroll semantics."""

    def __init__(self, clock: Optional[FakeClock] = None):
        self.clock = clock or FakeClock()
        self.source_events: Dict[str, Dict[str, Any]] = {}
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.other_events: List[Dict[str, Any]] = []
        self.entities: Dict[tuple, Dict[str, Any]] = {}
        self.owners_response: Dict[str, List[str]] = {
            "folders": [],
            "tasks": [],
            "users": [],
        }
        self.users: List[Dict[str, Any]] = []
        self.studio_settings: Dict[str, Any] = {
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
        self.project_settings: Dict[str, Any] = {}
        self.fail_in_progress: bool = False
        self.fail_final_update: bool = False
        self.job_counter: int = 0
        self.enroll_calls: List[Dict[str, Any]] = []
        self.reject_events_filter: bool = False
        self.fail_update_entity: bool = False
        self.entity_updates: List[Dict[str, Any]] = []

    def add_source_event(
        self,
        event_id: str,
        topic: str,
        project_name: str,
        created_at: float,
        payload: Optional[Dict[str, Any]] = None,
        summary: Optional[Dict[str, Any]] = None,
        user: Optional[str] = "alice",
        sender: Optional[str] = None,
        sender_type: Optional[str] = "api",
    ) -> Dict[str, Any]:
        """Add an AYON change event to the store."""
        event = {
            "id": event_id,
            "topic": topic,
            "project_name": project_name,
            "project": project_name,
            "createdAt": float(created_at),
            "created_at": float(created_at),
            "payload": payload or {},
            "summary": summary or {},
            "user": user,
            "sender": sender,
            "sender_type": sender_type,
            "senderType": sender_type,
        }
        self.source_events[event_id] = event
        return event

    def enroll_event_job(
        self,
        source_topic: Any,
        target_topic: str,
        sender: str,
        sequential: bool = True,
        max_retries: int = 3,
        events_filter: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Enroll an event job following F17 and sequential semantics."""
        self.enroll_calls.append({"events_filter": events_filter})
        if events_filter is not None and self.reject_events_filter:
            raise RuntimeError("Simulated server rejection of events_filter")
        now = float(self.clock())
        topics = (
            [source_topic]
            if isinstance(source_topic, str)
            else list(source_topic)
        )

        # Check sequential constraint:
        # If any job is held by another sender in progress or failed with
        # retries remaining, sequential enroll returns nothing.
        if sequential:
            for job in self.jobs.values():
                if job.get("sender") != sender:
                    status = job.get("status")
                    retries = job.get("retries", 0)
                    if status in ("in_progress", "pending"):
                        return None
                    if status == "failed" and retries <= max_retries:
                        return None

            # If own sender has an unfinished job (pending or in_progress),
            # return it first.
            for job in self.jobs.values():
                if job.get("sender") == sender:
                    status = job.get("status")
                    if status in ("in_progress", "pending"):
                        return dict(job)

        # Find eligible source events ordered by createdAt ascending
        eligible = [
            e
            for e in self.source_events.values()
            if e.get("topic") in topics
            and evaluate_query_filter(events_filter, e)
        ]
        eligible.sort(key=lambda e: float(e.get("createdAt", 0.0)))

        for src in eligible:
            src_id = src["id"]
            # Check existing target job for this source event
            existing = None
            for j in self.jobs.values():
                if j.get("dependsOn") == src_id:
                    existing = j
                    break

            if existing is None:
                # Create new target job
                self.job_counter += 1
                job_id = f"job-{self.job_counter}"
                new_job = {
                    "id": job_id,
                    "dependsOn": src_id,
                    "topic": target_topic,
                    "sender": sender,
                    "status": "pending",
                    "summary": {},
                    "description": "",
                    "retries": 0,
                    "createdAt": now,
                    "updatedAt": now,
                    "project_name": (
                        src.get("project_name") or src.get("project")
                    ),
                    "project": src.get("project_name") or src.get("project"),
                }
                self.jobs[job_id] = new_job
                return dict(new_job)

            # If existing job is failed with retries remaining, restart it
            if (
                existing.get("status") == "failed"
                and existing.get("retries", 0) <= max_retries
            ):
                existing["retries"] = existing.get("retries", 0) + 1
                existing["status"] = "pending"
                existing["sender"] = sender
                existing["updatedAt"] = now
                return dict(existing)

        return None

    def update_event(
        self,
        event_id: str,
        status: Optional[str] = None,
        description: Optional[str] = None,
        summary: Optional[Dict[str, Any]] = None,
        retries: Optional[int] = None,
        project_name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Update an event job in the store."""
        if self.fail_in_progress and status == "in_progress":
            raise RuntimeError("Simulated AYON failure on in_progress")
        if self.fail_final_update and status in ("finished", "failed"):
            self.fail_final_update = False
            raise RuntimeError("Simulated AYON failure on final update")

        now = float(self.clock())
        job = self.jobs.get(event_id)
        if job:
            if status is not None:
                job["status"] = status
            if description is not None:
                job["description"] = description
            if summary is not None:
                job.setdefault("summary", {}).update(summary)
            if retries is not None:
                job["retries"] = retries
            if project_name is not None:
                job["project_name"] = project_name
            if "sender" in kwargs:
                job["sender"] = kwargs["sender"]
            job["updatedAt"] = now
            return

        # Check other events
        for e in self.other_events:
            if e.get("id") == event_id:
                if summary is not None:
                    e.setdefault("summary", {}).update(summary)
                return

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch event by id."""
        if event_id in self.source_events:
            return dict(self.source_events[event_id])
        if event_id in self.jobs:
            return dict(self.jobs[event_id])
        for e in self.other_events:
            if e.get("id") == event_id:
                return dict(e)
        return None

    def get_events(
        self,
        topics: Optional[List[str]] = None,
        sender: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        project_names: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """Filter events in the store."""
        all_events = (
            list(self.source_events.values())
            + list(self.jobs.values())
            + self.other_events
        )
        res = []
        for e in all_events:
            if topics and e.get("topic") not in topics:
                continue
            if sender and e.get("sender") != sender:
                continue
            if statuses and e.get("status") not in statuses:
                continue
            if project_names:
                p = e.get("project_name") or e.get("project")
                if p not in project_names:
                    continue
            res.append(dict(e))
        return res

    def get_users(self) -> List[Dict[str, Any]]:
        return list(self.users)

    def dispatch_event(
        self,
        topic: str,
        project_name: Optional[str] = None,
        summary: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """Dispatch a gate or general event."""
        now = float(self.clock())
        self.disp_counter = getattr(self, "disp_counter", 0) + 1
        event_id = f"disp-{self.disp_counter}"
        event = {
            "id": event_id,
            "topic": topic,
            "project_name": project_name,
            "summary": summary or {},
            "createdAt": now,
        }
        self.other_events.append(event)
        res = MagicMock()
        res.data = {"id": event_id}
        return res

    # Entity lookup methods
    def get_task_by_id(
        self, project_name: str, task_id: str
    ) -> Optional[Dict[str, Any]]:
        return self.entities.get(("task", task_id))

    def get_folder_by_id(
        self, project_name: str, folder_id: str
    ) -> Optional[Dict[str, Any]]:
        return self.entities.get(("folder", folder_id))

    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.entities.get(("user", user_id))

    def _update_entity(
        self, kind: str, entity_id: str, data: Optional[Dict[str, Any]]
    ) -> None:
        if self.fail_update_entity:
            raise RuntimeError("Simulated AYON failure storing kitsuId")
        self.entity_updates.append(
            {"kind": kind, "id": entity_id, "data": dict(data or {})}
        )
        ent = self.entities.get((kind, entity_id))
        if ent is not None and data is not None:
            ent["data"] = dict(data)

    def update_folder(
        self, project_name: str, folder_id: str, **kwargs: Any
    ) -> None:
        self._update_entity("folder", folder_id, kwargs.get("data"))

    def update_task(
        self, project_name: str, task_id: str, **kwargs: Any
    ) -> None:
        self._update_entity("task", task_id, kwargs.get("data"))

    def get(self, url: str) -> Any:
        if "kitsu-owners" in url and "kitsu_id=" in url:
            parts = url.split("kitsu_id=")
            target_kitsu_id = parts[1].split("&")[0] if len(parts) > 1 else ""
            folders, tasks, users = [], [], []
            for (ent_type, ent_id), ent in self.entities.items():
                data = ent.get("data") or {}
                if data.get("kitsuId") == target_kitsu_id:
                    if ent_type == "folder":
                        folders.append(ent_id)
                    elif ent_type == "task":
                        tasks.append(ent_id)
                    elif ent_type == "user":
                        users.append(ent_id)
            res = MagicMock()
            res.data = {
                "folders": folders,
                "tasks": tasks,
                "users": users,
            }
            return res

        if "/users" in url or url.endswith("/users"):
            if getattr(self, "fail_get_users", False):
                raise RuntimeError("Simulated failure fetching users")
            res = MagicMock()
            res.data = list(self.users)
            return res

        res = MagicMock()
        res.data = self.owners_response
        return res

    def post(self, url: str, **kwargs: Any) -> Any:
        if url == "enroll":
            if (
                getattr(self, "fail_filter_enroll", False)
                and "filter" in kwargs
            ):
                res = MagicMock()
                res.status_code = 422
                res.text = "Unprocessable Entity: invalid filter"
                return res
            source_topic = kwargs.get("sourceTopic")
            target_topic = kwargs.get("targetTopic")
            sender = kwargs.get("sender")
            sequential = kwargs.get("sequential")
            max_retries = kwargs.get("maxRetries")
            events_filter = kwargs.get("filter")
            job = self.enroll_event_job(
                source_topic=source_topic,
                target_topic=target_topic,
                sender=sender,
                sequential=sequential,
                max_retries=max_retries,
                events_filter=events_filter,
            )
            res = MagicMock()
            if job:
                res.status_code = 200
                res.data = job
            else:
                res.status_code = 204
                res.data = None
            return res

        res = MagicMock()
        res.status_code = 200
        res.data = {}
        return res

    def get_service_addon_name(self) -> str:
        return "kitsu"

    def get_service_addon_version(self) -> str:
        return "1.2.4"

    def get_addon_project_settings(
        self,
        addon_name: str,
        addon_version: str,
        project_name: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self.project_settings.get(project_name, {})

    def get_addon_settings(
        self,
        addon_name: str,
        addon_version: str,
        project_name: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if project_name is None:
            return self.studio_settings
        return self.project_settings.get(project_name, {})

    def get_service_addon_settings(self) -> Dict[str, Any]:
        return self.studio_settings


class FakeKitsuWriter:
    """Mock writer for Kitsu status operations."""

    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.statuses: List[Dict[str, Any]] = [
            {"id": "st-wip", "name": "WIP", "archived": False},
            {"id": "st-done", "name": "Done", "archived": False},
            {"id": "st-app", "name": "Approved", "archived": False},
        ]
        self.comments: List[Dict[str, Any]] = []
        self.persons: List[Dict[str, Any]] = []
        self.assigned: List[Dict[str, Any]] = []
        self.unassigned: List[Dict[str, Any]] = []
        self.updated_fields: List[Dict[str, Any]] = []
        self.error_on_get_task: Optional[Exception] = None
        self.error_on_comment: Optional[Exception] = None
        self.error_on_assign: Optional[Exception] = None
        self.error_on_unassign: Optional[Exception] = None
        self.error_on_update_fields: Optional[Exception] = None
        self._slice3_init()

    def get_task(self, kitsu_id: str) -> Dict[str, Any]:
        if self.error_on_get_task:
            raise self.error_on_get_task
        task = self.tasks.get(kitsu_id)
        if not task:
            raise KitsuWriterError(
                "not_found", f"Task {kitsu_id} not found", http_status=404
            )
        task_copy = dict(task)
        task_copy.setdefault("type", "Task")
        return task_copy

    def get_entity(self, kitsu_id: str) -> Dict[str, Any]:
        if getattr(self, "error_on_get_entity", None):
            raise self.error_on_get_entity
        return self.get_task(kitsu_id)

    def task_statuses(self) -> List[Dict[str, Any]]:
        return list(self.statuses)

    def all_persons(self) -> List[Dict[str, Any]]:
        return list(self.persons)

    def assign(
        self, task: Dict[str, Any] | str, person_id: str
    ) -> None:
        if self.error_on_assign:
            raise self.error_on_assign
        task_id = task.get("id") if isinstance(task, dict) else task
        self.assigned.append({"task_id": task_id, "person_id": person_id})
        if task_id in self.tasks:
            assignees = set(self.tasks[task_id].get("assignees", []))
            assignees.add(person_id)
            self.tasks[task_id]["assignees"] = sorted(assignees)

    def unassign(
        self, task: Dict[str, Any] | str, person_id: str
    ) -> None:
        if self.error_on_unassign:
            raise self.error_on_unassign
        task_id = task.get("id") if isinstance(task, dict) else task
        self.unassigned.append({"task_id": task_id, "person_id": person_id})
        if task_id in self.tasks:
            assignees = set(self.tasks[task_id].get("assignees", []))
            assignees.discard(person_id)
            self.tasks[task_id]["assignees"] = sorted(assignees)

    def update_entity_fields(
        self,
        entity: Dict[str, Any] | str,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        if self.error_on_update_fields:
            raise self.error_on_update_fields
        kitsu_id = entity.get("id") if isinstance(entity, dict) else entity
        self.get_entity(kitsu_id)
        self.updated_fields.append(
            {"kitsu_id": kitsu_id, "fields": dict(fields)}
        )
        if kitsu_id in self.tasks:
            target = self.tasks[kitsu_id]
            data = target.setdefault("data", {})
            for k, v in fields.items():
                if k.startswith("data."):
                    data[k[5:]] = v
                else:
                    target[k] = v
        return {"id": kitsu_id, "fields": fields}

    def comment_status(
        self, task: Dict[str, Any], status: Dict[str, Any], text: str
    ) -> Dict[str, Any]:
        if self.error_on_comment:
            raise self.error_on_comment
        self.comments.append(
            {"task": task, "status": status, "text": text}
        )
        task["task_status_id"] = status["id"]
        kitsu_id = task.get("id")
        if kitsu_id and kitsu_id in self.tasks:
            self.tasks[kitsu_id]["task_status_id"] = status["id"]
        return {"id": f"comment-{len(self.comments)}"}

    # ------------------------------------------------------------------
    # Slice 3: creation, siblings, rename, removal, counts
    # ------------------------------------------------------------------

    def _slice3_init(self) -> None:
        if hasattr(self, "created"):
            return
        self.created: List[Dict[str, Any]] = []
        self.renamed: List[Dict[str, Any]] = []
        self.removed: List[Dict[str, Any]] = []
        self.kitsu_task_types: List[Dict[str, Any]] = [
            {"id": "tt-anim", "name": "Animation"},
            {"id": "tt-comp", "name": "Compositing"},
        ]
        self.siblings: Dict[tuple, List[Dict[str, Any]]] = {}
        self.entity_tasks: Dict[str, List[Dict[str, Any]]] = {}
        self.deletion_counts: Dict[str, Dict[str, int]] = {}
        self.error_on_create: Optional[Exception] = None
        self.error_on_rename: Optional[Exception] = None
        self.error_on_remove: Optional[Exception] = None
        self.create_counter = 0

    def task_types(
        self, project_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        self._slice3_init()
        return list(self.kitsu_task_types)

    def get_siblings(
        self,
        entity_type: str,
        project_id: str,
        parent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._slice3_init()
        return list(self.siblings.get((entity_type, parent_id), []))

    def get_tasks_for_entity(
        self, entity_id: str, parent_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        self._slice3_init()
        return list(self.entity_tasks.get(entity_id, []))

    def _new_id(self) -> str:
        self.create_counter += 1
        return f"kt-new-{self.create_counter}"

    def create_entity(
        self,
        entity_type: str,
        project_id: str,
        name: str,
        parent_id: Optional[str] = None,
        *,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._slice3_init()
        if self.error_on_create:
            raise self.error_on_create
        new = {
            "id": self._new_id(),
            "type": entity_type,
            "name": name,
            "project_id": project_id,
            "parent_id": parent_id,
            "data": data,
        }
        self.created.append(dict(new))
        self.tasks[new["id"]] = new
        self.siblings.setdefault((entity_type, parent_id), []).append(new)
        return dict(new)

    def create_task(
        self,
        entity_id: str,
        task_type_id: str,
        name: Optional[str] = None,
        project_id: Optional[str] = None,
        *,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        self._slice3_init()
        if self.error_on_create:
            raise self.error_on_create
        new = {
            "id": self._new_id(),
            "type": "Task",
            "name": name,
            "entity_id": entity_id,
            "task_type_id": task_type_id,
            "project_id": project_id,
            "data": data,
        }
        self.created.append(dict(new))
        self.tasks[new["id"]] = new
        self.entity_tasks.setdefault(entity_id, []).append(new)
        return dict(new)

    def rename_entity(
        self,
        entity: Dict[str, Any] | str,
        new_name: str,
        is_task: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._slice3_init()
        if self.error_on_rename:
            raise self.error_on_rename
        kitsu_id = entity.get("id") if isinstance(entity, dict) else entity
        payload = {"name": new_name}
        self.renamed.append(
            {"kitsu_id": kitsu_id, "payload": payload, "is_task": is_task}
        )
        if kitsu_id in self.tasks:
            self.tasks[kitsu_id]["name"] = new_name
        return {"id": kitsu_id, **payload}

    def remove_entity(
        self,
        entity: Dict[str, Any] | str,
        entity_type: Optional[str] = None,
    ) -> None:
        self._slice3_init()
        if self.error_on_remove:
            raise self.error_on_remove
        kitsu_id = entity.get("id") if isinstance(entity, dict) else entity
        self.removed.append(
            {"kitsu_id": kitsu_id, "type": entity_type, "force": False}
        )
        self.tasks.pop(kitsu_id, None)

    def get_deletion_counts(
        self, kitsu_id: str, entity_type: str
    ) -> Dict[str, int]:
        self._slice3_init()
        return dict(
            self.deletion_counts.get(
                kitsu_id, {"comments": 0, "previews": 0, "children": 0}
            )
        )


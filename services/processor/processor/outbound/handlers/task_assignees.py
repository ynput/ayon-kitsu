"""Task assignees outbound sync handler (Task 19.2).

Validates: Requirements 7.1, 7.3, 7.4, 7.6, 7.7, 9.1, 9.2, 13.2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..constants import (
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_SKIPPED,
)
from ..conflict import decide_field
from ..kitsu_writer import ERROR_REJECTED, KitsuWriterError
from ..mapping import kitsu_person_owner, resolve_assignees
from ..models import JobContext, JobResult, failed_result
from ..planning import plan_assignee_update

logger = logging.getLogger(__name__)


def _person_name(p_rec: Any, fallback_id: str) -> str:
    """Format Zou person display name (Requirement 7.4)."""
    if isinstance(p_rec, dict):
        if p_rec.get("name"):
            return str(p_rec["name"])
        first = str(p_rec.get("first_name", "")).strip()
        last = str(p_rec.get("last_name", "")).strip()
        full = f"{first} {last}".strip()
        if full:
            return full
        if p_rec.get("label"):
            return str(p_rec["label"])
    return str(fallback_id)


def handle_task_assignees(ctx: JobContext) -> JobResult:
    """Apply an entity.task.assignees_changed event to Kitsu.

    Args:
        ctx: JobContext holding event, resolver, writer, etc.

    Returns:
        JobResult instance.
    """

    prior_writes: List[Dict[str, Any]] = list(
        getattr(ctx, "prior_writes", []) or []
    )
    event = ctx.event
    summary = event.get("summary") or {}
    payload = event.get("payload") or {}
    entity_id = ctx.entity_id or summary.get("entityId")
    project_name = ctx.project_name
    username = event.get("user")

    # 1. Resolve identity
    id_res = ctx.identity_resolver.resolve(
        project_name=project_name,
        entity_type="task",
        entity_id=entity_id,
        expected_kind="task",
        kitsu_project_id=getattr(ctx, "kitsu_project_id", None),
    )
    if not id_res["ok"]:
        if id_res.get("outcome") == "skip":
            skip_details = {
                "reason": id_res["reason"],
                "entity_id": entity_id,
            }
            if prior_writes:
                skip_details["writes"] = prior_writes
            return JobResult(
                decision=DECISION_SKIPPED,
                details=skip_details,
                writes=prior_writes,
                kitsu_id=id_res.get("kitsu_id"),
                entity_type="Task",
            )
        retryable = bool(id_res.get("retryable"))
        err_kind = id_res.get("error_kind")
        http_st = id_res.get("http_status")
        return failed_result(
            ctx,
            id_res["reason"],
            writes=prior_writes,
            not_written=getattr(ctx, "prior_not_written", None),
            retryable=retryable,
            error_kind=err_kind,
            http_status=http_st,
            kitsu_id=id_res.get("kitsu_id"),
            entity_type="Task",
        )

    kitsu_id = id_res["kitsu"]["id"]

    # 2. Fetch Kitsu task and persons
    try:
        kitsu_task = ctx.writer.get_task(kitsu_id)
        kitsu_persons = ctx.writer.all_persons()
    except KitsuWriterError as exc:
        return failed_result(
            ctx,
            str(exc),
            writes=prior_writes,
            not_written=getattr(ctx, "prior_not_written", None),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # 3. Fetch AYON users
    try:
        ayon_users = _fetch_ayon_users(ctx)
    except Exception as exc:
        raw_new = payload.get("newValue")
        if raw_new is None:
            raw_new = payload.get("assignees", [])
        new_assignees = (
            raw_new if isinstance(raw_new, list) else [str(raw_new)]
        )
        not_written = getattr(ctx, "prior_not_written", None)
        if not not_written:
            written_names = {
                w.get("person_name")
                for w in prior_writes
                if isinstance(w, dict) and "person_name" in w
            }
            rem = [u for u in new_assignees if u not in written_names]
            not_written = {"assignees": rem} if rem else None
        return failed_result(
            ctx,
            f"Failed to fetch AYON users: {exc}",
            writes=prior_writes,
            not_written=not_written,
            retryable=True,
            error_kind="server_error",
            kitsu_id=kitsu_id,
            entity_type="Task",
            error=str(exc),
        )

    # 4. Resolve assignees
    raw_new = payload.get("newValue")
    if raw_new is None:
        raw_new = payload.get("assignees", [])
    new_assignees = raw_new if isinstance(raw_new, list) else [str(raw_new)]

    resolve_res = resolve_assignees(new_assignees, ayon_users, kitsu_persons)
    resolved_map = resolve_res["resolved"]
    unresolved_map = resolve_res["unresolved"]
    resolved_new_ids = sorted(resolved_map.values())

    # 5. Determine managed Kitsu person IDs (excluding persons whose mapped
    # AYON owner is in unresolved_map so a requested user whose forward
    # resolution failed is not unassigned).
    managed_ids_list: List[str] = []
    for p in kitsu_persons:
        if isinstance(p, dict):
            owner = kitsu_person_owner(p, ayon_users)
            if owner is not None and owner not in unresolved_map:
                managed_ids_list.append(p["id"])
    managed_ids = sorted(set(managed_ids_list))

    raw_assignees = kitsu_task.get("assignees", [])
    current_ids = sorted(
        set(p.get("id") if isinstance(p, dict) else p for p in raw_assignees)
    )
    pending = getattr(ctx, "pending_assignee_write", None)
    if pending and pending["kitsu_id"] == kitsu_id:
        write = pending["write"]
        assigned = write["person_id"] in current_ids
        if assigned == (write["action"] == "assign"):
            prior_writes.append(write)
    ctx.pending_assignee_write = None
    managed_current_ids = sorted(set(current_ids) & set(managed_ids))

    # 6. Conflict check against oldValue (accounting for prior writes)
    raw_old = payload.get("oldValue")
    has_prev = raw_old is not None
    prev_ids: Optional[List[str]] = None
    if has_prev:
        old_list = raw_old if isinstance(raw_old, list) else [str(raw_old)]
        old_res = resolve_assignees(old_list, ayon_users, kitsu_persons)
        prev_set = set(old_res["resolved"].values())
        for w in prior_writes:
            if w.get("action") == "assign" and "person_id" in w:
                prev_set.add(w["person_id"])
            elif w.get("action") == "unassign" and "person_id" in w:
                prev_set.discard(w["person_id"])
        prev_ids = sorted(prev_set)

    field_dec = decide_field(
        "assignees",
        prev_ids,
        managed_current_ids,
        resolved_new_ids,
        has_previous=has_prev,
        policy=ctx.conflict_policy,
    )
    action = field_dec["action"]

    # In-sync check (Requirement 9.7)
    if action == "skip_in_sync":
        if not unresolved_map:
            skip_details = {
                "reason": "already in sync",
                "field": "assignees",
                "kitsu_id": kitsu_id,
                "entity_type": "Task",
            }
            if prior_writes:
                skip_details["writes"] = prior_writes
            return JobResult(
                decision=DECISION_SKIPPED,
                details=skip_details,
                writes=prior_writes,
                kitsu_id=kitsu_id,
                entity_type="Task",
            )
        # Unresolved assignees with no writes needed still finish (7.3)
        applied_details = {
            "kitsu_entity_type": "Task",
            "kitsu_id": kitsu_id,
            "unresolved_assignees": sorted(unresolved_map.keys()),
        }
        if prior_writes:
            applied_details["writes"] = prior_writes
        return JobResult(
            decision=DECISION_APPLIED,
            details=applied_details,
            writes=prior_writes,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # Conflict kitsu wins: pull inbound (Requirement 9.4)
    if action == "conflict_keep_kitsu":
        if ctx.processor is not None:
            try:
                ctx.processor.pull_kitsu_task(kitsu_id, kitsu_task)
            except Exception as exc:
                logger.error("Could not pull kitsu task on conflict: %s", exc)
                return failed_result(
                    ctx,
                    f"Inbound pull on conflict failed: {exc}",
                    writes=prior_writes,
                    retryable=True,
                    error_kind=ERROR_REJECTED,
                    kitsu_id=kitsu_id,
                    entity_type="Task",
                )

        c_details = {
            "field": "assignees",
            "policy": ctx.conflict_policy,
            "previous": prev_ids,
            "kitsu_current": managed_current_ids,
            "rejected": resolved_new_ids,
            "kitsu_id": kitsu_id,
            "entity_type": "Task",
        }
        if unresolved_map:
            c_details["unresolved_assignees"] = sorted(unresolved_map.keys())
        if prior_writes:
            c_details["writes"] = prior_writes
        return JobResult(
            decision=DECISION_CONFLICT,
            details=c_details,
            writes=prior_writes,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # 7. Plan assignee updates
    plan = plan_assignee_update(current_ids, resolved_new_ids, managed_ids)
    to_add = plan["add"]
    to_remove = plan["remove"]

    # Loop guard check
    guard = ctx.loop_guard_check(entity_id, "assignees")
    if not guard["allowed"]:
        skip_details = {
            "reason": "loop suspected",
            "entity_id": entity_id,
            "kitsu_id": kitsu_id,
            "category": "task_assignees",
        }
        if prior_writes:
            skip_details["writes"] = prior_writes
        return JobResult(
            decision=DECISION_SKIPPED,
            details=skip_details,
            writes=prior_writes,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # 8. Apply updates via writer
    persons_by_id = {
        p["id"]: p for p in kitsu_persons if isinstance(p, dict) and "id" in p
    }

    writes = list(prior_writes)
    commit_fn = getattr(ctx, "loop_guard_commit", None)
    cur_ids = set(current_ids)
    operations = (
        ("assign", ctx.writer.assign, to_add),
        ("unassign", ctx.writer.unassign, to_remove),
    )
    try:
        for operation, send, person_ids in operations:
            for person_id in person_ids:
                next_ids = cur_ids.copy()
                if operation == "assign":
                    next_ids.add(person_id)
                else:
                    next_ids.discard(person_id)
                write = {
                    "field": "assignees",
                    "action": operation,
                    "person_id": person_id,
                    "person_name": _person_name(
                        persons_by_id.get(person_id), person_id
                    ),
                    "before": sorted(
                        _person_name(persons_by_id.get(pid), pid)
                        for pid in cur_ids
                    ),
                    "sent": sorted(
                        _person_name(persons_by_id.get(pid), pid)
                        for pid in next_ids
                    ),
                }
                ctx.pending_assignee_write = {
                    "kitsu_id": kitsu_id,
                    "write": write,
                }
                send(kitsu_task, person_id)
                ctx.pending_assignee_write = None
                writes.append(write)
                cur_ids = next_ids
                if callable(commit_fn):
                    commit_fn()
    except KitsuWriterError as exc:
        if not exc.retryable:
            ctx.pending_assignee_write = None
        written_ids = {
            w.get("person_id")
            for w in writes
            if isinstance(w, dict) and "person_id" in w
        }
        rem_add = [
            _person_name(persons_by_id.get(pid, {}), pid)
            for pid in to_add
            if pid not in written_ids
        ]
        rem_rm = [
            _person_name(persons_by_id.get(pid, {}), pid)
            for pid in to_remove
            if pid not in written_ids
        ]
        rem_all = rem_add + rem_rm
        not_written = {"assignees": rem_all} if rem_all else None
        return failed_result(
            ctx,
            str(exc),
            writes=writes,
            not_written=not_written,
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # 9. Format description and result
    all_added_ids = [
        w["person_id"]
        for w in writes
        if isinstance(w, dict)
        and w.get("action") == "assign"
        and "person_id" in w
    ]
    all_removed_ids = [
        w["person_id"]
        for w in writes
        if isinstance(w, dict)
        and w.get("action") == "unassign"
        and "person_id" in w
    ]
    added_records = [
        persons_by_id.get(pid, {"id": pid, "name": pid})
        for pid in all_added_ids
    ]
    removed_records = [
        persons_by_id.get(pid, {"id": pid, "name": pid})
        for pid in all_removed_ids
    ]

    before_names = sorted(
        _person_name(persons_by_id.get(pid, {}), pid) for pid in current_ids
    )
    sent_names = sorted(
        _person_name(persons_by_id.get(pid, {}), pid) for pid in cur_ids
    )

    initial_before = (
        prior_writes[0].get("before")
        if (
            prior_writes
            and isinstance(prior_writes[0], dict)
            and prior_writes[0].get("before") is not None
        )
        else before_names
    )

    details = {
        "kitsu_entity_type": "Task",
        "kitsu_id": kitsu_id,
        "writes": [
            {
                "field": "assignees",
                "before": initial_before,
                "sent": sent_names,
            }
        ],
        "added_assignees": added_records,
        "removed_assignees": removed_records,
    }
    if unresolved_map:
        details["unresolved_assignees"] = sorted(unresolved_map.keys())
    if action == "write_no_previous":
        details["no_previous_value"] = "assignees"
    if not username:
        details["no_user"] = True

    if action == "conflict_overwrite":
        return JobResult(
            decision=DECISION_CONFLICT,
            details={
                "field": "assignees",
                "policy": ctx.conflict_policy,
                "kitsu_current": managed_current_ids,
                "written": resolved_new_ids,
                "writes": writes,
                "added_assignees": added_records,
                "removed_assignees": removed_records,
                "unresolved_assignees": sorted(unresolved_map.keys())
                if unresolved_map
                else None,
                "kitsu_id": kitsu_id,
                "entity_type": "Task",
            },
            writes=writes,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    return JobResult(
        decision=DECISION_APPLIED,
        details=details,
        writes=writes,
        kitsu_id=kitsu_id,
        entity_type="Task",
    )


def _fetch_ayon_users(ctx: JobContext) -> List[Dict[str, Any]]:
    """Fetch AYON users via addon /users endpoint (Requirements 7.1-7.3)."""
    client = getattr(
        ctx,
        "ayon_client",
        getattr(ctx.identity_resolver, "ayon_client", None),
    )
    if client is None:
        return []

    entrypoint = getattr(
        getattr(ctx, "processor", None),
        "entrypoint",
        getattr(ctx.identity_resolver, "entrypoint", ""),
    )
    endpoint = f"{entrypoint}/users" if entrypoint else "/users"

    if hasattr(client, "get"):
        res = client.get(endpoint)
        if hasattr(res, "raise_for_status") and callable(res.raise_for_status):
            res.raise_for_status()
        st = getattr(res, "status_code", getattr(res, "status", None))
        if isinstance(st, int) and st >= 400:
            raise RuntimeError(f"HTTP {st} fetching AYON users")
        data = getattr(res, "data", res)
        if callable(getattr(data, "json", None)):
            try:
                data = data.json()
            except Exception:
                pass
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            if "users" in data and isinstance(data["users"], list):
                return list(data["users"])
            if "error" in data or "detail" in data or "message" in data:
                err_msg = (
                    data.get("detail")
                    or data.get("error")
                    or data.get("message")
                )
                raise RuntimeError(f"Error fetching AYON users: {err_msg}")
        raise ValueError(
            f"Unexpected response fetching AYON users: {type(data).__name__}"
        )

    if hasattr(client, "users") and isinstance(client.users, list):
        return list(client.users)

    if hasattr(client, "get_users"):
        return list(client.get_users())

    return []

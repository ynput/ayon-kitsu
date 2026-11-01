"""Task status outbound sync handler (Task 10.2).

Validates: Requirements 5.4, 5.9, 6.1, 6.3, 6.4, 6.6, 6.7, 6.8, 6.9,
9.1, 9.4, 9.5, 9.6, 9.7, 9.8, 13.2.
"""

import logging
from typing import Any, Dict, List, Optional

from ..constants import (
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    DECISION_SKIPPED,
    ERROR_REJECTED,
)
from ..conflict import decide_field
from ..describe import describe_job, status_comment_text
from ..kitsu_writer import KitsuWriterError
from ..mapping import map_status

logger = logging.getLogger(__name__)


def handle_task_status(ctx: Any) -> Any:
    """Apply an entity.task.status_changed event to Kitsu.

    Args:
        ctx: JobContext holding the event, resolver, writer, etc.

    Returns:
        JobResult instance.
    """
    from ..runner import JobResult

    event = ctx.event
    summary = event.get("summary") or {}
    payload = event.get("payload") or {}
    entity_id = ctx.entity_id or summary.get("entityId")
    project_name = ctx.project_name
    new_val = payload.get("newValue") or payload.get("status")
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
            desc = describe_job(
                DECISION_SKIPPED,
                {"reason": id_res["reason"], "entity_id": entity_id},
            )
            return JobResult(
                decision=DECISION_SKIPPED,
                description=desc,
                kitsu_id=id_res.get("kitsu_id"),
                entity_type="Task",
            )
        # Failure
        retryable = bool(id_res.get("retryable"))
        err_kind = id_res.get("error_kind")
        http_st = id_res.get("http_status")
        unwritten = (
            [{"field": "task_status_id", "ayonValue": new_val}]
            if new_val is not None
            else []
        )
        details = {
            "reason": id_res["reason"],
            "error": id_res["reason"],
            "retryable": retryable,
            "error_kind": err_kind,
            "http_status": http_st,
            "attempt": ctx.attempt,
            "kitsu_id": id_res.get("kitsu_id"),
            "entity_id": entity_id,
            "category": "task_status",
            "unwritten": unwritten,
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=retryable,
            error_kind=err_kind,
            http_status=http_st,
            kitsu_id=id_res.get("kitsu_id"),
            entity_type="Task",
            not_written=unwritten,
        )

    kitsu_id = id_res["kitsu"]["id"]

    # 2. Fetch Kitsu task and statuses
    try:
        kitsu_task = ctx.writer.get_task(kitsu_id)
        statuses = ctx.writer.task_statuses()
    except KitsuWriterError as exc:
        unwritten = (
            [{"field": "task_status_id", "ayonValue": new_val}]
            if new_val is not None
            else []
        )
        details = {
            "reason": str(exc),
            "error": str(exc),
            "retryable": exc.retryable,
            "error_kind": exc.kind,
            "http_status": exc.http_status,
            "attempt": ctx.attempt,
            "kitsu_id": kitsu_id,
            "entity_id": entity_id,
            "category": "task_status",
            "unwritten": unwritten,
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type="Task",
            not_written=unwritten,
        )

    # 3. Map new status
    new_map = map_status(new_val, statuses)
    if not new_map["ok"]:
        err_msg = (
            f"status '{new_val}' is {new_map['error']} in Kitsu "
            f"(matches: {new_map['count']})"
        )
        unwritten = [{"field": "task_status_id", "ayonValue": new_val}]
        details = {
            "reason": err_msg,
            "error": err_msg,
            "retryable": False,
            "error_kind": ERROR_REJECTED,
            "attempt": ctx.attempt,
            "kitsu_id": kitsu_id,
            "entity_id": entity_id,
            "category": "task_status",
            "unwritten": unwritten,
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=False,
            error_kind=ERROR_REJECTED,
            kitsu_id=kitsu_id,
            entity_type="Task",
            not_written=unwritten,
        )

    # 4. Map old status
    old_val = payload.get("oldValue")
    has_prev = old_val is not None
    prev_id = None
    no_prev_note: Optional[str] = None
    if has_prev:
        prev_map = map_status(old_val, statuses)
        if prev_map["ok"]:
            prev_id = prev_map["status"]["id"]
        else:
            # Unmatched old value treated as no previous value and noted
            has_prev = False
            no_prev_note = f"old status '{old_val}' had no match in Kitsu"

    # 5. Decide field
    kitsu_status_id = kitsu_task.get("task_status_id")
    target_status_id = new_map["status"]["id"]
    field_dec = decide_field(
        "task_status_id",
        prev_id,
        kitsu_status_id,
        target_status_id,
        has_previous=has_prev,
        policy=ctx.conflict_policy,
    )
    action = field_dec["action"]

    # In-sync check (Requirement 9.7)
    if action == "skip_in_sync":
        desc = describe_job(
            DECISION_SKIPPED,
            {
                "reason": "already in sync",
                "field": "task_status_id",
                "kitsu_id": kitsu_id,
                "entity_type": "Task",
            },
        )
        return JobResult(
            decision=DECISION_SKIPPED,
            description=desc,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # Conflict kitsu wins: pull inbound (Requirement 9.4)
    if action == "conflict_keep_kitsu":
        if ctx.processor is not None:
            pull_fn = getattr(ctx.processor, "pull_kitsu_task", None)
            try:
                res = None
                if callable(pull_fn):
                    res = pull_fn(kitsu_id, kitsu_task)
                else:
                    from ...update_from_kitsu import create_or_update_task

                    proj_id = ""
                    if isinstance(kitsu_task, dict):
                        proj_id = kitsu_task.get("project_id", "")
                    res = create_or_update_task(
                        ctx.processor,
                        {
                            "task_id": kitsu_id,
                            "project_id": proj_id,
                        },
                    )
                if res is not None:
                    st = getattr(
                        res, "status_code", getattr(res, "status", 200)
                    )
                    if isinstance(st, int) and st >= 400:
                        raise RuntimeError(
                            f"Inbound pull returned error status {st}"
                        )
            except Exception as exc:
                logger.error(
                    "Could not pull kitsu task on conflict: %s", exc
                )
                return JobResult(
                    decision=DECISION_FAILED,
                    description=describe_job(
                        DECISION_FAILED,
                        {
                            "reason": (
                                f"Inbound pull on conflict failed: {exc}"
                            ),
                            "retryable": True,
                            "error_kind": ERROR_REJECTED,
                            "attempt": ctx.attempt,
                            "kitsu_id": kitsu_id,
                            "entity_id": entity_id,
                            "category": "task_status",
                        },
                    ),
                    retryable=True,
                    error_kind=ERROR_REJECTED,
                    kitsu_id=kitsu_id,
                    entity_type="Task",
                )

        c_details = {
            "field": "task_status_id",
            "policy": ctx.conflict_policy,
            "previous": prev_id,
            "kitsu_current": kitsu_status_id,
            "rejected": target_status_id,
            "kitsu_id": kitsu_id,
            "entity_type": "Task",
        }
        if not username:
            c_details["no_user"] = True
        desc = describe_job(DECISION_CONFLICT, c_details)
        return JobResult(
            decision=DECISION_CONFLICT,
            description=desc,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # Write / Write_no_previous / Conflict_overwrite
    # Check loop guard
    guard = ctx.loop_guard_check(entity_id, "task_status_id")
    if not guard["allowed"]:
        desc = describe_job(
            DECISION_SKIPPED,
            {
                "reason": "loop suspected",
                "entity_id": entity_id,
                "kitsu_id": kitsu_id,
                "category": "task_status",
            },
        )
        return JobResult(
            decision=DECISION_SKIPPED,
            description=desc,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # Call writer.comment_status
    username = event.get("user")
    comment_text = status_comment_text(new_val, username)
    try:
        ctx.writer.comment_status(
            kitsu_task, new_map["status"], text=comment_text
        )
        commit_fn = getattr(ctx, "loop_guard_commit", None)
        if callable(commit_fn):
            commit_fn()
    except KitsuWriterError as exc:
        unwritten = [{"field": "task_status_id", "ayonValue": new_val}]
        details = {
            "reason": str(exc),
            "error": str(exc),
            "retryable": exc.retryable,
            "error_kind": exc.kind,
            "http_status": exc.http_status,
            "attempt": ctx.attempt,
            "kitsu_id": kitsu_id,
            "entity_id": entity_id,
            "category": "task_status",
            "unwritten": unwritten,
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type="Task",
            not_written=unwritten,
        )

    writes: List[Dict[str, Any]] = [
        {
            "field": "task_status_id",
            "before": kitsu_status_id,
            "sent": target_status_id,
        }
    ]

    if action == "conflict_overwrite":
        desc = describe_job(
            DECISION_CONFLICT,
            {
                "field": "task_status_id",
                "policy": ctx.conflict_policy,
                "kitsu_current": kitsu_status_id,
                "written": target_status_id,
                "writes": writes,
                "kitsu_id": kitsu_id,
                "entity_type": "Task",
            },
        )
        return JobResult(
            decision=DECISION_CONFLICT,
            description=desc,
            writes=writes,
            kitsu_id=kitsu_id,
            entity_type="Task",
        )

    # Applied
    details = {
        "kitsu_entity_type": "Task",
        "kitsu_id": kitsu_id,
        "writes": writes,
    }
    if action == "write_no_previous" or no_prev_note:
        details["no_previous_value"] = "task_status_id"
    if not username:
        details["no_user"] = True
    desc = describe_job(DECISION_APPLIED, details)
    return JobResult(
        decision=DECISION_APPLIED,
        description=desc,
        writes=writes,
        kitsu_id=kitsu_id,
        entity_type="Task",
    )

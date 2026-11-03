"""Entity and task creation outbound sync handler (Task 25.2).

Validates: Requirements 11.1, 11.2, 11.3, 11.5, 11.6, 11.7, 11.8, 11.9,
11.10, 13.2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..constants import (
    DECISION_APPLIED,
    DECISION_SKIPPED,
    ERROR_REJECTED,
    ERROR_UNREACHABLE,
    SKIP_ALREADY_PAIRED,
    SKIP_ENTITY_GONE,
    STRUCTURAL_KITSU_IDS,
)
from ..kitsu_writer import KitsuWriterError
from ..models import JobContext, JobResult, failed_result
from ..planning import CREATION_FOLDER_TYPES, plan_creation

logger = logging.getLogger(__name__)


def _store_kitsu_id_on_ayon(
    ayon_client: Any,
    project_name: str,
    entity_id: str,
    is_task: bool,
    existing_data: Dict[str, Any],
    new_kitsu_id: str,
) -> None:
    """Store new_kitsu_id in data.kitsuId on the AYON entity (11.1, 11.2)."""
    if hasattr(ayon_client, "set_sender_type"):
        try:
            ayon_client.set_sender_type("kitsu_sync")
        except Exception:
            pass

    new_data = dict(existing_data or {})
    new_data["kitsuId"] = new_kitsu_id

    if is_task:
        if callable(getattr(ayon_client, "update_task", None)):
            ayon_client.update_task(project_name, entity_id, data=new_data)
            return
        if hasattr(ayon_client, "patch"):
            resp = ayon_client.patch(
                f"projects/{project_name}/tasks/{entity_id}",
                data=new_data,
            )
            if resp is not None:
                if hasattr(resp, "raise_for_status"):
                    resp.raise_for_status()
                elif hasattr(resp, "status_code") and resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}")
            return
        raise RuntimeError("AYON client does not support update_task")

    if callable(getattr(ayon_client, "update_folder", None)):
        ayon_client.update_folder(project_name, entity_id, data=new_data)
        return
    if hasattr(ayon_client, "patch"):
        resp = ayon_client.patch(
            f"projects/{project_name}/folders/{entity_id}",
            data=new_data,
        )
        if resp is not None:
            if hasattr(resp, "raise_for_status"):
                resp.raise_for_status()
            elif hasattr(resp, "status_code") and resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")
        return
    raise RuntimeError("AYON client does not support update_folder")


def handle_creation(ctx: JobContext) -> JobResult:
    """Apply entity.folder.created or entity.task.created to Kitsu.

    Args:
        ctx: JobContext holding event, resolver, writer, etc.

    Returns:
        JobResult instance.
    """

    event = ctx.event
    topic = event.get("topic", "")
    summary = event.get("summary") or {}
    entity_id = ctx.entity_id or summary.get("entityId") or ""
    project_name = ctx.project_name
    kitsu_project_id = getattr(ctx, "kitsu_project_id", None) or ""
    is_task = "task" in topic
    expected_kind = "task" if is_task else "folder"
    default_entity_type = "Task" if is_task else "Folder"
    username = event.get("user")

    # 1. Read created AYON entity at processing time
    try:
        ayon_entity = ctx.identity_resolver.get_ayon_entity(
            project_name, expected_kind, entity_id
        )
    except Exception as exc:
        return failed_result(
            ctx,
            f"Failed to read AYON {expected_kind}: {exc}",
            retryable=True,
            error_kind=ERROR_UNREACHABLE,
            entity_type=default_entity_type,
            error=str(exc),
        )

    if not ayon_entity:
        reason = SKIP_ENTITY_GONE.format(entity_id=entity_id)
        return JobResult(
            decision=DECISION_SKIPPED,
            details={"reason": reason, "entity_id": entity_id},
            entity_type=default_entity_type,
        )

    if not is_task:
        default_entity_type = str(
            ayon_entity.get("folderType")
            or ayon_entity.get("folder_type")
            or "Folder"
        )

    def _skip(reason: str) -> JobResult:
        return JobResult(
            decision=DECISION_SKIPPED,
            details={"reason": reason, "entity_id": entity_id},
            entity_type=default_entity_type,
        )

    # 2. Skip if already paired (Requirement 11.7)
    kitsu_id = str(
        (ayon_entity.get("data") or {}).get("kitsuId") or ""
    ).strip()
    if kitsu_id:
        return _skip(SKIP_ALREADY_PAIRED)

    # 3. Read parent AYON folder if referenced
    parent_folder_id: Optional[str] = (
        (ayon_entity.get("folderId") or ayon_entity.get("folder_id"))
        if is_task
        else (ayon_entity.get("parentId") or ayon_entity.get("parent_id"))
    )
    parent: Optional[Dict[str, Any]] = None
    if parent_folder_id:
        try:
            parent = ctx.identity_resolver.get_ayon_entity(
                project_name, "folder", str(parent_folder_id)
            )
        except Exception as exc:
            return failed_result(
                ctx,
                f"Failed to read parent AYON folder: {exc}",
                retryable=True,
                error_kind=ERROR_UNREACHABLE,
                entity_type=default_entity_type,
                error=str(exc),
            )

    # Normalized parent: only Kitsu-relevant keys (never the AYON id)
    parent_info: Optional[Dict[str, Any]] = None
    if isinstance(parent, dict):
        p_type = parent.get("folderType") or parent.get("folder_type")
        p_kitsu_id = str(
            (parent.get("data") or {}).get("kitsuId") or ""
        ).strip()
        p_name = str(parent.get("name") or "")

        # Validate paired entity parent identity through IdentityResolver
        # (Requirements 11.2, 11.3, 3.5, 3.7, 3.8). Structural parents (e.g.
        # asset types or sequence roots) are validated by plan_creation.
        if (
            p_type in CREATION_FOLDER_TYPES
            and p_kitsu_id
            and p_kitsu_id not in STRUCTURAL_KITSU_IDS
        ):
            parent_res = ctx.identity_resolver.resolve(
                project_name=project_name,
                entity_type="folder",
                entity_id=str(parent_folder_id),
                expected_kind="folder",
                kitsu_project_id=ctx.kitsu_project_id,
            )
            if isinstance(parent_res, dict) and not parent_res.get("ok"):
                outcome = parent_res.get("outcome")
                reason = (
                    parent_res.get("reason")
                    or "parent folder identity is invalid"
                )
                if outcome == "fail":
                    return failed_result(
                        ctx,
                        f"Parent folder identity invalid: {reason}",
                        retryable=parent_res.get("retryable", False),
                        error_kind=parent_res.get(
                            "error_kind", ERROR_REJECTED
                        ),
                        http_status=parent_res.get("http_status"),
                        entity_type=default_entity_type,
                        error=str(parent_res.get("error") or reason),
                    )
                return JobResult(
                    decision=DECISION_SKIPPED,
                    details={
                        "reason": f"Parent folder skipped: {reason}",
                        "entity_id": entity_id,
                        "category": "entity_creation",
                    },
                    retryable=False,
                    entity_type=default_entity_type,
                )

        parent_info = {
            "folder_type": p_type,
            "kitsu_id": p_kitsu_id,
            "name": p_name,
        }

    name = str(ayon_entity.get("name") or "")
    kitsu_id = str(
        (ayon_entity.get("data") or {}).get("kitsuId") or ""
    ).strip()
    task_type: Optional[str] = (
        str(ayon_entity.get("taskType") or ayon_entity.get("task_type") or "")
        if is_task
        else None
    )
    folder_type = None if is_task else default_entity_type

    def _plan(siblings: List[Dict[str, Any]], tts: List[Dict[str, Any]]):
        return plan_creation(
            name=name,
            folder_type=folder_type,
            task_type=task_type,
            kitsu_id=kitsu_id or None,
            parent=parent_info,
            siblings=siblings,
            kitsu_task_types=tts,
        )

    # 4. Preliminary plan without Kitsu reads (already paired, type,
    # parent rule). Tasks need task types, so only check pairing first.
    if kitsu_id or not is_task:
        prelim = _plan([], [])
        if prelim["action"] == "skip":
            return _skip(prelim["reason"])
    if is_task and not (parent_info or {}).get("kitsu_id"):
        return _skip(_plan([], [])["reason"])

    # 4. Fetch Kitsu task types and siblings, then plan (11.2, 11.9)
    try:
        if is_task:
            task_types = ctx.writer.task_types(kitsu_project_id) or []
            prelim = _plan([], task_types)
            if prelim["action"] == "skip":
                return _skip(prelim["reason"])
            siblings = ctx.writer.get_tasks_for_entity(
                prelim["parent_id"],
                parent_type=(parent_info or {}).get("folder_type"),
            )
            plan = _plan(siblings or [], task_types)
        else:
            siblings = ctx.writer.get_siblings(
                entity_type=prelim["entity_type"],
                project_id=kitsu_project_id,
                parent_id=prelim["parent_id"],
            )
            plan = _plan(siblings or [], [])
    except KitsuWriterError as exc:
        return failed_result(
            ctx,
            str(exc),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            entity_type=default_entity_type,
        )

    if plan["action"] == "skip":
        return _skip(plan["reason"])

    target_type = "Task" if is_task else plan["entity_type"]
    target_name = plan["name"]

    # 5. Loop guard check
    guard = ctx.loop_guard_check(entity_id, "entity_creation")
    if not guard["allowed"]:
        return JobResult(
            decision=DECISION_SKIPPED,
            details={
                "reason": "loop suspected",
                "entity_id": entity_id,
                "category": "entity_creation",
            },
            entity_type=target_type,
        )

    # 6. Coordinate in-flight creation interval and create in Kitsu
    proc = getattr(ctx, "processor", None)
    if proc:
        if hasattr(proc, "start_in_flight_creation"):
            proc.start_in_flight_creation()
        elif hasattr(proc, "register_in_flight_creation"):
            try:
                proc.register_in_flight_creation()
            except TypeError:
                pass

    new_kitsu_id: Optional[str] = None
    try:
        try:
            if is_task:
                created = ctx.writer.create_task(
                    entity_id=plan["parent_id"],
                    task_type_id=plan["task_type_id"],
                    name=target_name,
                    project_id=kitsu_project_id,
                )
            else:
                created = ctx.writer.create_entity(
                    entity_type=target_type,
                    project_id=kitsu_project_id,
                    name=target_name,
                    parent_id=plan["parent_id"],
                )
            commit_fn = getattr(ctx, "loop_guard_commit", None)
            if callable(commit_fn):
                commit_fn()
        except KitsuWriterError as exc:
            unwritten = {"name": target_name}
            return failed_result(
                ctx,
                str(exc),
                retryable=exc.retryable,
                error_kind=exc.kind,
                http_status=exc.http_status,
                entity_type=target_type,
                not_written=unwritten,
            )

        new_kitsu_id = str((created or {}).get("id") or "")
        writes: List[Dict[str, Any]] = [
            {
                "field": "kitsuId",
                "before": None,
                "sent": new_kitsu_id,
            }
        ]

        # 7. Store data.kitsuId on AYON entity (Requirement 11.1, 11.2, 11.6)
        if proc and hasattr(proc, "register_in_flight_creation"):
            proc.register_in_flight_creation(new_kitsu_id)

        ayon_client = getattr(ctx.identity_resolver, "ayon_client", None)
        try:
            _store_kitsu_id_on_ayon(
                ayon_client=ayon_client,
                project_name=project_name,
                entity_id=entity_id,
                is_task=is_task,
                existing_data=ayon_entity.get("data") or {},
                new_kitsu_id=new_kitsu_id,
            )
        except Exception as exc:
            # Leave created Kitsu entity in place and fail with both ids (11.6)
            err_msg = (
                f"created Kitsu {target_type} {new_kitsu_id} for AYON entity "
                f"{entity_id}, but storing data.kitsuId failed: {exc}"
            )
            return failed_result(
                ctx,
                err_msg,
                retryable=False,
                error_kind=ERROR_REJECTED,
                kitsu_id=new_kitsu_id,
                entity_type=target_type,
                writes=writes,
                not_written={"data.kitsuId": new_kitsu_id},
            )
    finally:
        if proc and hasattr(proc, "finish_in_flight_creation"):
            proc.finish_in_flight_creation(new_kitsu_id)

    # 8. Applied
    applied_details: Dict[str, Any] = {
        "kitsu_entity_type": target_type,
        "kitsu_id": new_kitsu_id,
        "writes": writes,
        "message": f"created {target_type} '{target_name}'",
    }
    if not username:
        applied_details["no_user"] = True

    return JobResult(
        decision=DECISION_APPLIED,
        details=applied_details,
        writes=writes,
        kitsu_id=new_kitsu_id,
        entity_type=target_type,
    )

"""Entity and task deletion outbound sync handler (Task 25.4).

Validates: Requirements 12.2, 12.3, 12.4, 12.6, 12.7, 12.8, 13.2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..constants import (
    DECISION_APPLIED,
    DECISION_FAILED,
    DECISION_SKIPPED,
    ERROR_REJECTED,
    ERROR_UNREACHABLE,
)
from ..describe import describe_job
from ..identity_rules import (
    KITSU_ID_OK,
    KITSU_ID_STRUCTURAL,
    validate_kitsu_id,
)
from ..kitsu_writer import KitsuWriterError
from ..planning import plan_deletion

logger = logging.getLogger(__name__)


def _extract_kitsu_id_from_event(event: Dict[str, Any]) -> Optional[str]:
    """Extract kitsuId from deletion event payload or summary (12.2, 12.8)."""
    payload = event.get("payload") or {}
    if isinstance(payload, dict):
        entity_data = (
            payload.get("entityData") or payload.get("entity_data") or {}
        )
        if isinstance(entity_data, dict):
            data_dict = entity_data.get("data") or {}
            if isinstance(data_dict, dict) and data_dict.get("kitsuId"):
                return str(data_dict["kitsuId"]).strip()
            if entity_data.get("kitsuId"):
                return str(entity_data["kitsuId"]).strip()
        p_data = payload.get("data") or {}
        if isinstance(p_data, dict) and p_data.get("kitsuId"):
            return str(p_data["kitsuId"]).strip()
        if payload.get("kitsuId"):
            return str(payload["kitsuId"]).strip()

    summary = event.get("summary") or {}
    if isinstance(summary, dict) and summary.get("kitsuId"):
        return str(summary["kitsuId"]).strip()

    return None


def handle_deletion(ctx: Any) -> Any:
    """Apply entity.folder.deleted or entity.task.deleted to Kitsu.

    Args:
        ctx: JobContext holding event, resolver, writer, etc.

    Returns:
        JobResult instance.
    """
    from ..runner import JobResult

    event = ctx.event
    topic = event.get("topic", "")
    summary = event.get("summary") or {}
    payload = event.get("payload") or {}
    entity_id = ctx.entity_id or summary.get("entityId") or ""
    project_name = ctx.project_name

    # Guard against project and user deletion regardless of toggles (12.6)
    if topic in ("entity.project.deleted", "entity.user.deleted"):
        return JobResult(
            decision=DECISION_SKIPPED,
            description=describe_job(
                DECISION_SKIPPED,
                {
                    "reason": "project and person deletion is out of scope",
                    "entity_id": entity_id,
                },
            ),
        )

    is_task = "task" in topic
    expected_kind = "task" if is_task else "folder"
    default_entity_type = "Task" if is_task else "Folder"
    username = event.get("user")

    # 1. Extract kitsuId from deletion event payload (12.2, 12.8)
    raw_kitsu_id = _extract_kitsu_id_from_event(event)
    if not raw_kitsu_id and ctx.identity_resolver is not None:
        try:
            ayon_entity = ctx.identity_resolver.get_ayon_entity(
                project_name, expected_kind, entity_id
            )
            if isinstance(ayon_entity, dict):
                raw_kitsu_id = str(
                    (ayon_entity.get("data") or {}).get("kitsuId") or ""
                ).strip()
        except Exception as exc:
            details = {
                "reason": f"Failed to read AYON {expected_kind}: {exc}",
                "error": str(exc),
                "retryable": True,
                "error_kind": ERROR_UNREACHABLE,
                "attempt": ctx.attempt,
                "entity_id": entity_id,
                "category": "entity_deletion",
            }
            return JobResult(
                decision=DECISION_FAILED,
                description=describe_job(DECISION_FAILED, details),
                retryable=True,
                error_kind=ERROR_UNREACHABLE,
                entity_type=default_entity_type,
            )

    if not raw_kitsu_id:
        reason_msg = (
            f"kitsuId could not be determined for deleted AYON entity "
            f"{entity_id}"
        )
        details = {
            "reason": reason_msg,
            "error": reason_msg,
            "retryable": False,
            "error_kind": ERROR_REJECTED,
            "attempt": ctx.attempt,
            "entity_id": entity_id,
            "category": "entity_deletion",
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=False,
            error_kind=ERROR_REJECTED,
            entity_type=default_entity_type,
        )

    val_res = validate_kitsu_id(raw_kitsu_id, entity_id)
    if val_res["result"] == KITSU_ID_STRUCTURAL:
        return JobResult(
            decision=DECISION_SKIPPED,
            description=describe_job(
                DECISION_SKIPPED,
                {"reason": val_res["reason"], "entity_id": entity_id},
            ),
            entity_type=default_entity_type,
        )
    if val_res["result"] != KITSU_ID_OK:
        reason_msg = (
            f"kitsuId could not be determined for deleted AYON entity "
            f"{entity_id}"
        )
        details = {
            "reason": reason_msg,
            "error": reason_msg,
            "retryable": False,
            "error_kind": ERROR_REJECTED,
            "attempt": ctx.attempt,
            "entity_id": entity_id,
            "category": "entity_deletion",
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=False,
            error_kind=ERROR_REJECTED,
            entity_type=default_entity_type,
        )

    kitsu_id = str(val_res["kitsu_id"])

    # 2. Fetch Kitsu entity and deletion counts (12.2, 12.3, 12.7)
    entity_data = (
        (payload.get("entityData") or payload.get("entity_data") or {})
        if isinstance(payload, dict)
        else {}
    )
    fallback_name = (
        str(entity_data.get("name") or "")
        if isinstance(entity_data, dict)
        else ""
    )
    fallback_type = (
        "Task"
        if is_task
        else str(
            (
                entity_data.get("folderType")
                if isinstance(entity_data, dict)
                else ""
            )
            or "Folder"
        )
    )

    try:
        kitsu_entity = (
            ctx.writer.get_task(kitsu_id)
            if is_task
            else ctx.writer.get_entity(kitsu_id)
        )
        k_proj = (kitsu_entity or {}).get("project_id")
        if ctx.kitsu_project_id and (
            not k_proj or k_proj != ctx.kitsu_project_id
        ):
            reason_msg = (
                f"Kitsu entity {kitsu_id} of AYON entity {entity_id} "
                f"belongs to Kitsu project {k_proj or 'unknown'}, expected "
                f"{ctx.kitsu_project_id}"
            )
            details = {
                "reason": reason_msg,
                "error": "project_mismatch",
                "retryable": False,
                "error_kind": ERROR_REJECTED,
                "attempt": ctx.attempt,
                "kitsu_id": kitsu_id,
                "entity_id": entity_id,
                "category": "entity_deletion",
            }
            return JobResult(
                decision=DECISION_FAILED,
                description=describe_job(DECISION_FAILED, details),
                retryable=False,
                error_kind=ERROR_REJECTED,
                kitsu_id=kitsu_id,
                entity_type=fallback_type,
            )

        k_type = (kitsu_entity or {}).get("type")
        if is_task and (not k_type or k_type != "Task"):
            reason_msg = (
                f"Kitsu entity {kitsu_id} of AYON entity {entity_id} is a "
                f"{k_type or 'unknown entity'}, expected a Task"
            )
            details = {
                "reason": reason_msg,
                "error": "kind_mismatch",
                "retryable": False,
                "error_kind": ERROR_REJECTED,
                "attempt": ctx.attempt,
                "kitsu_id": kitsu_id,
                "entity_id": entity_id,
                "category": "entity_deletion",
            }
            return JobResult(
                decision=DECISION_FAILED,
                description=describe_job(DECISION_FAILED, details),
                retryable=False,
                error_kind=ERROR_REJECTED,
                kitsu_id=kitsu_id,
                entity_type=fallback_type,
            )
    except KitsuWriterError as exc:
        reason_msg = (
            f"operation delete on kitsu_id {kitsu_id} for AYON entity "
            f"{entity_id} failed: {exc}"
        )
        details = {
            "reason": reason_msg,
            "error": str(exc),
            "retryable": exc.retryable,
            "error_kind": exc.kind,
            "http_status": exc.http_status,
            "attempt": ctx.attempt,
            "kitsu_id": kitsu_id,
            "entity_id": entity_id,
            "category": "entity_deletion",
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type=fallback_type,
        )

    kitsu_name = str(
        (kitsu_entity or {}).get("name") or fallback_name or kitsu_id
    )
    kitsu_type = (
        "Task"
        if is_task
        else str((kitsu_entity or {}).get("type") or fallback_type)
    )

    # 2b. Check surviving owners in AYON
    if hasattr(ctx, "identity_resolver") and ctx.identity_resolver:
        try:
            owners = ctx.identity_resolver.get_kitsu_owners(
                project_name, kitsu_id
            )
            surviving = [
                fid for fid in owners.get("folders", []) if fid != entity_id
            ] + [
                tid for tid in owners.get("tasks", []) if tid != entity_id
            ]
            if surviving:
                reason_msg = (
                    f"Kitsu entity {kitsu_id} cannot be deleted: still owned "
                    f"by surviving AYON entity(ies) {surviving}"
                )
                details = {
                    "reason": reason_msg,
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                    "category": "entity_deletion",
                }
                return JobResult(
                    decision=DECISION_SKIPPED,
                    description=describe_job(DECISION_SKIPPED, details),
                    retryable=False,
                    kitsu_id=kitsu_id,
                    entity_type=fallback_type,
                )
        except Exception as exc:
            reason_msg = f"failed to query kitsu-owners for {kitsu_id}: {exc}"
            details = {
                "reason": reason_msg,
                "error": str(exc),
                "retryable": True,
                "error_kind": ERROR_UNREACHABLE,
                "attempt": ctx.attempt,
                "kitsu_id": kitsu_id,
                "entity_id": entity_id,
                "category": "entity_deletion",
            }
            return JobResult(
                decision=DECISION_FAILED,
                description=describe_job(DECISION_FAILED, details),
                retryable=True,
                error_kind=ERROR_UNREACHABLE,
                kitsu_id=kitsu_id,
                entity_type=fallback_type,
            )

    try:
        counts = ctx.writer.get_deletion_counts(kitsu_id, kitsu_type)
    except KitsuWriterError as exc:
        reason_msg = (
            f"operation delete on kitsu_id {kitsu_id} for AYON entity "
            f"{entity_id} failed: {exc}"
        )
        details = {
            "reason": reason_msg,
            "error": str(exc),
            "retryable": exc.retryable,
            "error_kind": exc.kind,
            "http_status": exc.http_status,
            "attempt": ctx.attempt,
            "kitsu_id": kitsu_id,
            "entity_id": entity_id,
            "category": "entity_deletion",
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type=fallback_type,
        )

    # 3. Evaluate deletion guard (Requirement 12.2, 12.3)
    plan = plan_deletion(counts=counts)
    if not plan["allowed"]:
        return JobResult(
            decision=DECISION_SKIPPED,
            description=describe_job(
                DECISION_SKIPPED,
                {
                    "reason": plan["reason"],
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                },
            ),
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    # 4. Check loop guard
    guard = ctx.loop_guard_check(entity_id, "entity_deletion")
    if not guard["allowed"]:
        return JobResult(
            decision=DECISION_SKIPPED,
            description=describe_job(
                DECISION_SKIPPED,
                {
                    "reason": "loop suspected",
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                    "category": "entity_deletion",
                },
            ),
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    # 5. Remove Kitsu entity without force=True (12.2, 12.3, 12.4, 12.7)
    try:
        ctx.writer.remove_entity(kitsu_entity, entity_type=kitsu_type)
        commit_fn = getattr(ctx, "loop_guard_commit", None)
        if callable(commit_fn):
            commit_fn()
    except KitsuWriterError as exc:
        reason_msg = (
            f"operation delete on kitsu_id {kitsu_id} for AYON entity "
            f"{entity_id} failed: {exc}"
        )
        details = {
            "reason": reason_msg,
            "error": str(exc),
            "retryable": exc.retryable,
            "error_kind": exc.kind,
            "http_status": exc.http_status,
            "attempt": ctx.attempt,
            "kitsu_id": kitsu_id,
            "entity_id": entity_id,
            "category": "entity_deletion",
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    writes: List[Dict[str, Any]] = [
        {
            "field": "deleted",
            "before": kitsu_name,
            "sent": True,
        }
    ]
    applied_details: Dict[str, Any] = {
        "kitsu_entity_type": kitsu_type,
        "kitsu_id": kitsu_id,
        "kitsu_name": kitsu_name,
        "ayon_entity_id": entity_id,
        "deleted": True,
        "writes": writes,
    }
    if not username:
        applied_details["no_user"] = True

    return JobResult(
        decision=DECISION_APPLIED,
        description=describe_job(DECISION_APPLIED, applied_details),
        writes=writes,
        kitsu_id=kitsu_id,
        entity_type=kitsu_type,
    )

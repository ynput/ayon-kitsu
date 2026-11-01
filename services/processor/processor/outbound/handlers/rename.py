"""Entity and task rename outbound sync handler (Task 25.3).

Validates: Requirements 12.1, 12.7, 13.2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..conflict import decide_field
from ..constants import (
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    DECISION_SKIPPED,
    ERROR_REJECTED,
)
from ..describe import describe_job
from ..kitsu_writer import KitsuWriterError
from ..planning import plan_rename

logger = logging.getLogger(__name__)


def handle_rename(ctx: Any) -> Any:
    """Apply folder/task renamed or label_changed events to Kitsu.

    Args:
        ctx: JobContext holding event, resolver, writer, etc.

    Returns:
        JobResult instance.
    """
    from ..runner import JobResult

    event = ctx.event
    topic = event.get("topic", "")
    summary = event.get("summary") or {}
    entity_id = ctx.entity_id or summary.get("entityId") or ""
    project_name = ctx.project_name
    is_task = "task" in topic
    expected_kind = "task" if is_task else "folder"
    default_entity_type = "Task" if is_task else "Folder"
    username = event.get("user")

    # 1. Resolve identity via IdentityResolver (Requirement 12.1)
    id_res = ctx.identity_resolver.resolve(
        project_name=project_name,
        entity_type=expected_kind,
        entity_id=entity_id,
        expected_kind=expected_kind,
        kitsu_project_id=getattr(ctx, "kitsu_project_id", None),
    )
    if not id_res["ok"]:
        if id_res.get("outcome") == "skip":
            return JobResult(
                decision=DECISION_SKIPPED,
                description=describe_job(
                    DECISION_SKIPPED,
                    {"reason": id_res["reason"], "entity_id": entity_id},
                ),
                kitsu_id=id_res.get("kitsu_id"),
                entity_type=default_entity_type,
            )
        retryable = bool(id_res.get("retryable"))
        err_kind = id_res.get("error_kind")
        http_st = id_res.get("http_status")
        k_id = id_res.get("kitsu_id")
        reason_msg = (
            f"operation rename on kitsu_id {k_id} for AYON entity "
            f"{entity_id} failed: {id_res['reason']}"
        )
        details = {
            "reason": reason_msg,
            "error": id_res["reason"],
            "retryable": retryable,
            "error_kind": err_kind,
            "http_status": http_st,
            "attempt": ctx.attempt,
            "kitsu_id": k_id,
            "entity_id": entity_id,
            "category": "entity_rename",
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=retryable,
            error_kind=err_kind,
            http_status=http_st,
            kitsu_id=k_id,
            entity_type=default_entity_type,
        )

    ayon_entity = id_res["ayon"]
    kitsu_entity = id_res["kitsu"]
    kitsu_id = str(kitsu_entity["id"])
    kitsu_type = str(
        kitsu_entity.get("type") or default_entity_type
    )
    prev_kitsu_name = str(kitsu_entity.get("name") or "")

    # 2. Plan rename from source event and current AYON entity (Req 12.1).
    # Preserve the rename/label_changed event's newValue if an intervening
    # inbound update echoed Kitsu's old name/label back onto the AYON entity.
    payload = event.get("payload") or {}
    has_new_val = isinstance(payload, dict) and "newValue" in payload
    new_val = payload.get("newValue") if has_new_val else None

    ayon_name = ayon_entity.get("name")
    ayon_label = ayon_entity.get("label")
    if has_new_val:
        if "label_changed" in topic:
            if isinstance(new_val, str) or new_val is None:
                ayon_label = new_val
            elif isinstance(new_val, dict) and "label" in new_val:
                ayon_label = new_val.get("label")
        elif "renamed" in topic:
            req_name = None
            if isinstance(new_val, str) and new_val:
                req_name = new_val
            elif isinstance(new_val, dict) and "name" in new_val:
                req_name = new_val.get("name")
            if req_name:
                if (
                    ayon_entity.get("name") != req_name
                    and ayon_label == prev_kitsu_name
                ):
                    ayon_label = None
                ayon_name = req_name

    plan = plan_rename(
        name=ayon_name,
        label=ayon_label,
    )
    target_name = plan["target_name"]
    if not target_name:
        return JobResult(
            decision=DECISION_SKIPPED,
            description=describe_job(
                DECISION_SKIPPED,
                {
                    "reason": "target name is empty",
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                },
            ),
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    has_old_val = isinstance(payload, dict) and "oldValue" in payload
    old_val = payload.get("oldValue") if has_old_val else None
    prev_name = None
    if has_old_val and old_val is not None:
        if "label_changed" in topic:
            if isinstance(old_val, str):
                old_label = old_val
            elif isinstance(old_val, dict) and "label" in old_val:
                old_label = old_val.get("label")
            else:
                old_label = None
            prev_name = plan_rename(
                name=ayon_entity.get("name"),
                label=old_label,
            )["target_name"]
        elif "renamed" in topic:
            if isinstance(old_val, str) and old_val:
                old_name = old_val
            elif isinstance(old_val, dict) and "name" in old_val:
                old_name = old_val.get("name")
            else:
                old_name = None
            prev_name = plan_rename(
                name=old_name,
                label=ayon_label,
            )["target_name"]
        elif isinstance(old_val, str) and old_val:
            prev_name = old_val

    has_prev = bool(prev_name)
    policy = getattr(ctx, "conflict_policy", None)
    if policy not in ("kitsu_wins", "ayon_wins"):
        policy = "kitsu_wins"

    field_dec = decide_field(
        "name",
        prev_name,
        prev_kitsu_name,
        target_name,
        has_previous=has_prev,
        policy=policy,
    )
    action = field_dec["action"]

    if action == "skip_in_sync":
        return JobResult(
            decision=DECISION_SKIPPED,
            description=describe_job(
                DECISION_SKIPPED,
                {
                    "reason": "already in sync",
                    "field": "name",
                    "kitsu_id": kitsu_id,
                    "entity_type": kitsu_type,
                },
            ),
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    if action == "conflict_keep_kitsu":
        if getattr(ctx, "processor", None) is not None:
            try:
                res = None
                proj_id = (
                    kitsu_entity.get("project_id", "")
                    if isinstance(kitsu_entity, dict)
                    else ""
                )
                if is_task:
                    pull_fn = getattr(ctx.processor, "pull_kitsu_task", None)
                    if callable(pull_fn):
                        res = pull_fn(kitsu_id, kitsu_entity)
                    else:
                        from ...update_from_kitsu import create_or_update_task

                        res = create_or_update_task(
                            ctx.processor,
                            {"task_id": kitsu_id, "project_id": proj_id},
                        )
                else:
                    k_type = kitsu_type.lower()
                    pull_fn = getattr(ctx.processor, "pull_kitsu_entity", None)
                    if callable(pull_fn):
                        res = pull_fn(kitsu_id, k_type, kitsu_entity)
                    else:
                        from ... import update_from_kitsu as ufk

                        if k_type == "shot":
                            res = ufk.create_or_update_shot(
                                ctx.processor,
                                {"shot_id": kitsu_id, "project_id": proj_id},
                            )
                        elif k_type == "asset":
                            res = ufk.create_or_update_asset(
                                ctx.processor,
                                {"asset_id": kitsu_id, "project_id": proj_id},
                            )
                        elif k_type == "sequence":
                            res = ufk.create_or_update_sequence(
                                ctx.processor,
                                {
                                    "sequence_id": kitsu_id,
                                    "project_id": proj_id,
                                },
                            )
                        elif k_type == "episode":
                            res = ufk.create_or_update_episode(
                                ctx.processor,
                                {
                                    "episode_id": kitsu_id,
                                    "project_id": proj_id,
                                },
                            )
                        elif k_type == "edit":
                            res = ufk.create_or_update_edit(
                                ctx.processor,
                                {"edit_id": kitsu_id, "project_id": proj_id},
                            )
                        elif k_type == "concept":
                            res = ufk.create_or_update_concept(
                                ctx.processor,
                                {
                                    "concept_id": kitsu_id,
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
                    "Could not pull kitsu entity on rename conflict: %s", exc
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
                            "category": "entity_rename",
                        },
                    ),
                    retryable=True,
                    error_kind=ERROR_REJECTED,
                    kitsu_id=kitsu_id,
                    entity_type=kitsu_type,
                )

        c_details: Dict[str, Any] = {
            "field": "name",
            "policy": policy,
            "previous": prev_name,
            "kitsu_current": prev_kitsu_name,
            "rejected": target_name,
            "kitsu_id": kitsu_id,
            "entity_type": kitsu_type,
        }
        if not username:
            c_details["no_user"] = True
        return JobResult(
            decision=DECISION_CONFLICT,
            description=describe_job(DECISION_CONFLICT, c_details),
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    # 3. Check loop guard
    guard = ctx.loop_guard_check(entity_id, "name")
    if not guard["allowed"]:
        return JobResult(
            decision=DECISION_SKIPPED,
            description=describe_job(
                DECISION_SKIPPED,
                {
                    "reason": "loop suspected",
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                    "category": "entity_rename",
                },
            ),
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    # 4. Write only 'name' via KitsuWriter.rename_entity (12.1, 12.7)
    try:
        ctx.writer.rename_entity(
            kitsu_entity, target_name, is_task=is_task
        )
        commit_fn = getattr(ctx, "loop_guard_commit", None)
        if callable(commit_fn):
            commit_fn()
    except KitsuWriterError as exc:
        unwritten = [{"field": "name", "ayonValue": target_name}]
        reason_msg = (
            f"operation rename on kitsu_id {kitsu_id} for AYON entity "
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
            "category": "entity_rename",
            "unwritten": unwritten,
        }
        return JobResult(
            decision=DECISION_FAILED,
            description=describe_job(DECISION_FAILED, details),
            retryable=exc.retryable,
            error_kind=exc.kind,
            http_status=exc.http_status,
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
            not_written=unwritten,
        )

    writes: List[Dict[str, Any]] = [
        {
            "field": "name",
            "before": prev_kitsu_name,
            "sent": target_name,
        }
    ]
    if action == "conflict_overwrite":
        c_over_details: Dict[str, Any] = {
            "field": "name",
            "policy": policy,
            "kitsu_current": prev_kitsu_name,
            "written": target_name,
            "writes": writes,
            "kitsu_id": kitsu_id,
            "entity_type": kitsu_type,
        }
        if not username:
            c_over_details["no_user"] = True
        return JobResult(
            decision=DECISION_CONFLICT,
            description=describe_job(DECISION_CONFLICT, c_over_details),
            writes=writes,
            kitsu_id=kitsu_id,
            entity_type=kitsu_type,
        )

    applied_details: Dict[str, Any] = {
        "kitsu_entity_type": kitsu_type,
        "kitsu_id": kitsu_id,
        "writes": writes,
        "previous_name": prev_kitsu_name,
        "new_name": target_name,
    }
    if action == "write_no_previous":
        applied_details["no_previous_value"] = "name"
    if not username:
        applied_details["no_user"] = True

    return JobResult(
        decision=DECISION_APPLIED,
        description=describe_job(DECISION_APPLIED, applied_details),
        writes=writes,
        kitsu_id=kitsu_id,
        entity_type=kitsu_type,
    )

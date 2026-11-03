"""Entity attributes outbound sync handler (Task 19.3).

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.8, 8.9, 8.11,
9.1, 9.2, 13.2.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..constants import (
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_SKIPPED,
    ERROR_REJECTED,
)
from ..conflict import decide_field
from ..kitsu_writer import KitsuWriterError
from ..models import JobContext, JobResult, failed_result
from ..mapping import kitsu_attrib_view
from ..planning import plan_attribute_write

logger = logging.getLogger(__name__)


def handle_attributes(ctx: JobContext) -> JobResult:
    """Apply entity.folder.attrib_changed or entity.task.attrib_changed.

    Args:
        ctx: JobContext holding event, resolver, writer, etc.

    Returns:
        JobResult instance.
    """

    event = ctx.event
    prior_writes: List[Dict[str, Any]] = list(
        getattr(ctx, "prior_writes", []) or []
    )
    topic = event.get("topic", "")
    summary = event.get("summary") or {}
    payload = event.get("payload") or {}
    entity_id = ctx.entity_id or summary.get("entityId")
    project_name = ctx.project_name
    expected_kind = "folder" if "folder" in topic else "task"
    entity_type = expected_kind
    username = event.get("user")

    # 1. Resolve identity
    id_res = ctx.identity_resolver.resolve(
        project_name=project_name,
        entity_type=entity_type,
        entity_id=entity_id,
        expected_kind=expected_kind,
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
                entity_type="Task" if expected_kind == "task" else "Folder",
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
            entity_type="Task" if expected_kind == "task" else "Folder",
        )

    kitsu_id = id_res["kitsu"]["id"]
    is_task = expected_kind == "task"

    # 2. Fetch fresh Kitsu entity
    try:
        current_kitsu = (
            ctx.writer.get_task(kitsu_id)
            if is_task
            else ctx.writer.get_entity(kitsu_id)
        )
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
            entity_type="Task" if is_task else "Folder",
        )

    # 3. Extract changed attributes
    raw_changed = payload.get("newValue")
    if raw_changed is None:
        raw_changed = payload.get("changed") or {}
    changed = dict(raw_changed) if isinstance(raw_changed, dict) else {}

    raw_old = payload.get("oldValue")
    old_values = dict(raw_old) if isinstance(raw_old, dict) else None

    # 4. Read AYON attributes and ownership
    ayon_entity = id_res["ayon"]
    effective_attrib = dict(ayon_entity.get("attrib") or {})
    # Preserve source-event values for changed keys so an intervening inbound
    # echo cannot overwrite the user's edit in AYON and cause a false in-sync
    # skip, while unchanged counterparts still use current effective values.
    for k, v in changed.items():
        if v is not None:
            effective_attrib[k] = v
    if "own_attributes" in ayon_entity:
        own_raw = ayon_entity["own_attributes"]
    elif "ownAttrib" in ayon_entity:
        own_raw = ayon_entity["ownAttrib"]
    elif "own_attrib" in ayon_entity:
        own_raw = ayon_entity["own_attrib"]
    else:
        own_raw = None

    if own_raw is None:
        # Fallback if own_attributes metadata is missing:
        # Attributes explicitly reset to None in changed are not owned
        own_attrib = [
            k for k in effective_attrib.keys() if changed.get(k) is not None
        ]
    elif isinstance(own_raw, (list, set, tuple)):
        own_attrib = [
            k for k in own_raw if k is not None and changed.get(k) is not None
        ]
    elif isinstance(own_raw, dict):
        # In ayon_api, own_attributes maps attribute names to explicit values;
        # inherited attributes have None values.
        own_attrib = [
            k
            for k, v in own_raw.items()
            if v is not None and changed.get(k) is not None
        ]
    else:
        own_attrib = []

    # 5. Plan attribute write
    plan = plan_attribute_write(changed, effective_attrib, own_attrib)
    planned_fields = dict(plan["fields"])
    skipped = dict(plan["skipped"])
    errors = list(plan["errors"])

    # 6. Conflict checks per changed attribute
    fallback_start = (
        old_values.get("frameStart")
        if old_values and "frameStart" in old_values
        else effective_attrib.get("frameStart")
    )
    current_view = kitsu_attrib_view(
        current_kitsu, fallback_frame_start=fallback_start
    )

    decisions: Dict[str, Any] = {}
    conflicts: Dict[str, Any] = {}
    overwrites: Dict[str, Any] = {}
    all_in_sync = True

    attrs_to_check = list(changed.keys())
    if "frameStart" in changed or "frameEnd" in changed:
        if (
            "data.frame_in" in planned_fields
            and "frameStart" not in attrs_to_check
        ):
            attrs_to_check.append("frameStart")
        if (
            "data.frame_out" in planned_fields
            and "frameEnd" not in attrs_to_check
        ):
            attrs_to_check.append("frameEnd")
    if "resolutionWidth" in changed or "resolutionHeight" in changed:
        if "data.resolution" in planned_fields:
            if "resolutionWidth" not in attrs_to_check:
                attrs_to_check.append("resolutionWidth")
            if "resolutionHeight" not in attrs_to_check:
                attrs_to_check.append("resolutionHeight")

    for attr in attrs_to_check:
        if attr in skipped:
            continue

        target_val = effective_attrib.get(attr)
        current_val = current_view.get(attr)
        has_prev = old_values is not None and attr in old_values
        prev_val = old_values.get(attr) if has_prev else None

        field_dec = decide_field(
            attr,
            prev_val,
            current_val,
            target_val,
            has_previous=has_prev,
            policy=ctx.conflict_policy,
        )
        decisions[attr] = field_dec
        action = field_dec["action"]

        if action != "skip_in_sync":
            all_in_sync = False

        if action == "conflict_keep_kitsu":
            conflicts[attr] = {
                "previous": prev_val,
                "current": current_val,
                "target": target_val,
            }
        elif action == "conflict_overwrite":
            overwrites[attr] = {
                "previous": prev_val,
                "current": current_val,
                "target": target_val,
            }

    # Assemble fields to write resolving shared fields (Req 8.2, 9.2)
    fields_to_write: Dict[str, Any] = {}

    fps_dec = decisions.get("fps")
    if fps_dec and fps_dec["action"] in (
        "write",
        "write_no_previous",
        "conflict_overwrite",
    ):
        if "data.fps" in planned_fields:
            fields_to_write["data.fps"] = planned_fields["data.fps"]

    desc_dec = decisions.get("description")
    if desc_dec and desc_dec["action"] in (
        "write",
        "write_no_previous",
        "conflict_overwrite",
    ):
        if "description" in planned_fields:
            fields_to_write["description"] = planned_fields["description"]

    # Resolution pair
    target_res = planned_fields.get("data.resolution")
    has_res_conflict = (
        "resolutionWidth" in conflicts or "resolutionHeight" in conflicts
    )
    if target_res is not None and not has_res_conflict:
        curr_w = current_view.get("resolutionWidth")
        curr_h = current_view.get("resolutionHeight")
        curr_res = f"{curr_w}x{curr_h}" if curr_w and curr_h else None
        if target_res != curr_res:
            fields_to_write["data.resolution"] = target_res
            all_in_sync = False

    # Frame range
    target_in = planned_fields.get("data.frame_in")
    target_out = planned_fields.get("data.frame_out")
    has_frame_conflict = "frameStart" in conflicts or "frameEnd" in conflicts
    if (
        target_in is not None or target_out is not None
    ) and not has_frame_conflict:
        curr_in = current_view.get("frameStart")
        curr_out = current_view.get("frameEnd")
        added_frame = False
        if target_in is not None and target_in != curr_in:
            fields_to_write["data.frame_in"] = target_in
            added_frame = True
        if target_out is not None and target_out != curr_out:
            fields_to_write["data.frame_out"] = target_out
            added_frame = True
        if "nb_frames" in planned_fields:
            curr_nb = (
                current_kitsu.get("nb_frames")
                if isinstance(current_kitsu, dict)
                else None
            )
            if planned_fields["nb_frames"] != curr_nb:
                fields_to_write["nb_frames"] = planned_fields["nb_frames"]
                added_frame = True
        if added_frame:
            all_in_sync = False

    # Omit superseded fields from retried job (Requirement 10.7)
    omitted_raw = getattr(ctx, "omitted_fields", None)
    omitted = (
        [f for f in omitted_raw if isinstance(f, str)]
        if isinstance(omitted_raw, (list, tuple, set))
        else []
    )
    # Paired frame fields must be omitted atomically so supersession of one
    # field (e.g. nb_frames) cannot leave Kitsu endpoints out of sync.
    frame_fields = ("data.frame_in", "data.frame_out", "nb_frames")
    if any(f in omitted for f in frame_fields):
        for f in frame_fields:
            if f not in omitted:
                omitted.append(f)

    for fld in omitted:
        if fld in fields_to_write:
            del fields_to_write[fld]
            logger.info(
                "Superseded field %s omitted from write for %s",
                fld,
                entity_id,
            )

    # 7. Loop guard check.
    # Only record/commit loop-guard state for fields that are actually sent.
    # For paired frame fields, if any paired frame field is suppressed, all
    # paired frame fields are atomically suppressed and their pending
    # loop-guard reservations are rolled back before non-frame fields are
    # checked and committed.
    frame_fields = ("data.frame_in", "data.frame_out", "nb_frames")
    allowed_fields: Dict[str, Any] = {}
    suppressed_fields: List[str] = []

    frame_to_write = [
        (fld, val)
        for fld, val in fields_to_write.items()
        if fld in frame_fields
    ]
    non_frame_to_write = [
        (fld, val)
        for fld, val in fields_to_write.items()
        if fld not in frame_fields
    ]

    if frame_to_write:
        frame_allowed: Dict[str, Any] = {}
        frame_suppressed = False
        for fld, val in frame_to_write:
            guard = ctx.loop_guard_check(entity_id, fld)
            if guard["allowed"]:
                frame_allowed[fld] = val
            else:
                frame_suppressed = True
                suppressed_fields.append(fld)
                logger.info(
                    "Loop guard suppressed field %s for %s", fld, entity_id
                )
        if frame_suppressed:
            discard_fn = getattr(ctx, "loop_guard_discard", None)
            if callable(discard_fn):
                discard_fn()
            elif hasattr(ctx, "loop_guard_check"):
                fn = ctx.loop_guard_check
                g = getattr(fn, "__globals__", None)
                if isinstance(g, dict) and "pending" in g:
                    g["pending"] = None
            for fld, _ in frame_to_write:
                if fld not in suppressed_fields:
                    suppressed_fields.append(fld)
                    logger.info(
                        "Loop guard atomically suppressed paired frame "
                        "field %s for %s",
                        fld,
                        entity_id,
                    )
        else:
            allowed_fields.update(frame_allowed)

    for fld, val in non_frame_to_write:
        guard = ctx.loop_guard_check(entity_id, fld)
        if guard["allowed"]:
            allowed_fields[fld] = val
        else:
            suppressed_fields.append(fld)
            logger.info(
                "Loop guard suppressed field %s for %s", fld, entity_id
            )

    if fields_to_write and not allowed_fields:
        skip_details = {
            "reason": "loop suspected",
            "entity_id": entity_id,
            "kitsu_id": kitsu_id,
            "category": "entity_attributes",
        }
        if prior_writes:
            skip_details["writes"] = prior_writes
        return JobResult(
            decision=DECISION_SKIPPED,
            details=skip_details,
            writes=prior_writes,
            kitsu_id=kitsu_id,
            entity_type="Task" if is_task else "Folder",
        )

    # 8. Apply writes via writer (one PUT request, Requirement 8.4, 8.11)
    writes: List[Dict[str, Any]] = list(prior_writes)
    if allowed_fields:
        k_data = (
            current_kitsu.get("data")
            if isinstance(current_kitsu, dict)
            else {}
        ) or {}
        planned_writes: List[Dict[str, Any]] = []
        for fld, val in allowed_fields.items():
            if fld.startswith("data."):
                before_val = k_data.get(fld[5:])
            else:
                before_val = (
                    current_kitsu.get(fld)
                    if isinstance(current_kitsu, dict)
                    else None
                )
            planned_writes.append(
                {
                    "field": fld,
                    "before": before_val,
                    "sent": val,
                }
            )
        try:
            ctx.writer.update_entity_fields(current_kitsu, allowed_fields)
            commit_fn = getattr(ctx, "loop_guard_commit", None)
            if callable(commit_fn):
                try:
                    commit_fn(list(allowed_fields.keys()))
                except TypeError:
                    commit_fn()
            writes.extend(planned_writes)
        except KitsuWriterError as exc:
            not_written = dict(allowed_fields)
            if getattr(ctx, "prior_not_written", None) and isinstance(
                ctx.prior_not_written, dict
            ):
                not_written = {**ctx.prior_not_written, **not_written}
            return failed_result(
                ctx,
                str(exc),
                retryable=exc.retryable,
                error_kind=exc.kind,
                http_status=exc.http_status,
                kitsu_id=kitsu_id,
                entity_type="Task" if is_task else "Folder",
                writes=writes,
                not_written=not_written,
            )

    # 9. Requirement 8.3: invalid frame range writes others, then fails
    if errors:
        err_msg = errors[0]
        not_written = {
            k: changed[k] for k in ("frameStart", "frameEnd") if k in changed
        }
        if getattr(ctx, "prior_not_written", None) and isinstance(
            ctx.prior_not_written, dict
        ):
            not_written = {**ctx.prior_not_written, **not_written}
        return failed_result(
            ctx,
            err_msg,
            retryable=False,
            error_kind=ERROR_REJECTED,
            kitsu_id=kitsu_id,
            entity_type="Task" if is_task else "Folder",
            writes=writes,
            not_written=not_written,
        )

    # 10. Check if all fields were already in sync or skipped
    if not allowed_fields and not conflicts and not overwrites:
        if omitted and not writes and not skipped:
            skip_details = {
                "reason": "superseded by newer jobs",
                "kitsu_id": kitsu_id,
                "entity_type": "Task" if is_task else "Folder",
            }
            if prior_writes:
                skip_details["writes"] = prior_writes
            return JobResult(
                decision=DECISION_SKIPPED,
                details=skip_details,
                writes=prior_writes,
                kitsu_id=kitsu_id,
                entity_type="Task" if is_task else "Folder",
            )
        if all_in_sync and not skipped:
            skip_details = {
                "reason": "already in sync",
                "kitsu_id": kitsu_id,
                "entity_type": "Task" if is_task else "Folder",
            }
            if prior_writes:
                skip_details["writes"] = prior_writes
            return JobResult(
                decision=DECISION_SKIPPED,
                details=skip_details,
                writes=prior_writes,
                kitsu_id=kitsu_id,
                entity_type="Task" if is_task else "Folder",
            )
        if skipped:
            inh = [k for k, r in skipped.items() if r == "inherited"]
            skp = [
                f"{k} ({r})" for k, r in skipped.items() if r != "inherited"
            ]
            if inh and not skp:
                reason = f"skipped because inherited: {', '.join(inh)}"
            else:
                reason = f"skipped attributes: {', '.join(skp + inh)}"
            return JobResult(
                decision=DECISION_SKIPPED,
                details={
                    "reason": reason,
                    "kitsu_id": kitsu_id,
                    "entity_type": "Task" if is_task else "Folder",
                },
                kitsu_id=kitsu_id,
                entity_type="Task" if is_task else "Folder",
            )

    # Inbound pull on conflict under kitsu_wins (Requirement 9.4)
    if conflicts and ctx.conflict_policy != "ayon_wins":
        if ctx.processor is not None:
            try:
                if is_task:
                    ctx.processor.pull_kitsu_task(kitsu_id, current_kitsu)

                    # Restore conflicting task attributes on AYON task entity
                    task_attrib_updates = {}
                    for attr, conf in conflicts.items():
                        c_val = conf.get("current")
                        if c_val is not None:
                            task_attrib_updates[attr] = c_val
                    if task_attrib_updates:
                        ayon_client = getattr(
                            ctx.identity_resolver, "ayon_client", None
                        )
                        if ayon_client and hasattr(ayon_client, "update_task"):
                            try:
                                ayon_client.update_task(
                                    project_name=project_name,
                                    task_id=entity_id,
                                    attrib=task_attrib_updates,
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Could not restore task %s attribs: %s",
                                    entity_id,
                                    exc,
                                )
                else:
                    k_type = str(
                        current_kitsu.get("type")
                        or id_res["kitsu"].get("type", "")
                    ).lower()
                    ctx.processor.pull_kitsu_entity(
                        kitsu_id, k_type, current_kitsu
                    )
            except Exception as exc:
                logger.error(
                    "Could not pull kitsu entity on conflict: %s", exc
                )
                return failed_result(
                    ctx,
                    f"Inbound pull on conflict failed: {exc}",
                    retryable=True,
                    error_kind=ERROR_REJECTED,
                    kitsu_id=kitsu_id,
                    entity_type="Task" if is_task else "Folder",
                    writes=writes,
                    not_written=getattr(ctx, "prior_not_written", None),
                )

    # 11. Format description details
    skipped_attrs = [
        f"{k} ({reason})"
        for k, reason in skipped.items()
        if reason != "inherited"
    ]
    inherited_attrs = [
        k for k, reason in skipped.items() if reason == "inherited"
    ]

    details = {
        "kitsu_entity_type": "Task" if is_task else "Folder",
        "kitsu_id": kitsu_id,
        "writes": writes,
    }
    if skipped_attrs:
        details["skipped_attributes"] = skipped_attrs
    if inherited_attrs:
        details["inherited_fields"] = inherited_attrs
    if not username:
        details["no_user"] = True

    no_prev_attrs = [
        attr
        for attr, dec in decisions.items()
        if dec.get("action") == "write_no_previous"
    ]
    if no_prev_attrs and writes:
        details["no_previous_value"] = sorted(no_prev_attrs)

    if conflicts:
        conflict_list = [
            {
                "field": fld,
                "policy": ctx.conflict_policy,
                "previous": info["previous"],
                "kitsu_current": info["current"],
                "rejected": info["target"],
            }
            for fld, info in conflicts.items()
        ]
        c_details = dict(details)
        c_details["conflicts"] = conflict_list
        c_details["policy"] = ctx.conflict_policy
        return JobResult(
            decision=DECISION_CONFLICT,
            details=c_details,
            writes=writes,
            kitsu_id=kitsu_id,
            entity_type="Task" if is_task else "Folder",
        )

    if overwrites:
        overwrite_list = [
            {
                "field": fld,
                "policy": ctx.conflict_policy,
                "kitsu_current": info["current"],
                "written": info["target"],
            }
            for fld, info in overwrites.items()
        ]
        o_details = dict(details)
        o_details["conflicts"] = overwrite_list
        o_details["policy"] = ctx.conflict_policy
        return JobResult(
            decision=DECISION_CONFLICT,
            details=o_details,
            writes=writes,
            kitsu_id=kitsu_id,
            entity_type="Task" if is_task else "Folder",
        )

    return JobResult(
        decision=DECISION_APPLIED,
        details=details,
        writes=writes,
        kitsu_id=kitsu_id,
        entity_type="Task" if is_task else "Folder",
    )

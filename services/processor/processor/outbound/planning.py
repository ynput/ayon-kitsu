"""Pure planning functions for Outbound_Sync updates.

This module is part of the pure core: it imports only the standard library,
takes and returns built-in values, reads no clock and performs no I/O
(Requirement 14.1).

It holds the Assignee update plan (Slice 2, Requirement 7.1, 7.4, 7.6),
the Attribute write plan (Slice 2, Requirement 8), and the Slice 3 plans
for Creation, Rename, and Deletion (Requirements 11 and 12).
"""

from __future__ import annotations

import math
from typing import Any

from .constants import (
    CREATION_FOLDER_TYPES,
    SKIP_ALREADY_PAIRED,
    STRUCTURAL_KITSU_IDS,
)
from .mapping import MAPPED_ATTRIBUTES


def plan_assignee_update(
    current_ids: list[str],
    resolved_ids: list[str],
    managed_ids: list[str],
) -> dict[str, list[str]]:
    """Plan additions and removals for Kitsu task assignees (7.1, 7.4, 7.6).

    Calculates changes to apply to a Kitsu task so that the set of assignees
    managed by AYON matches the resolved assignees from the AYON change event,
    while all unmanaged assignees (persons in Kitsu not resolvable to any
    AYON user) are strictly preserved (Property 15, Requirement 7.6).

    Formula:
        add = sorted(resolved_ids - current_ids)
        remove = sorted((current_ids & managed_ids) - resolved_ids)

    Args:
        current_ids: Kitsu person IDs currently assigned to the Kitsu task.
        resolved_ids: Kitsu person IDs resolved from the new AYON assignees
            (output of ``resolve_assignees``).
        managed_ids: Kitsu person IDs that resolve to an AYON user (persons
            for which ``kitsu_person_owner`` returns an AYON username).

    Returns:
        Dict with sorted ``add`` and ``remove`` person ID lists:
        ``{"add": [...], "remove": [...]}``.
    """
    current_set = set(current_ids)
    resolved_set = set(resolved_ids)
    managed_set = set(managed_ids)

    # Add resolved persons that are not currently assigned
    add = sorted(resolved_set - current_set)

    # Remove currently assigned persons that are managed by AYON but absent
    # from the resolved assignees. Unmanaged persons are NEVER removed.
    remove = sorted((current_set & managed_set) - resolved_set)

    return {"add": add, "remove": remove}


def merge_kitsu_data(
    current_data: dict | None,
    planned_fields: dict,
) -> dict[str, Any]:
    """Overlay planned data fields onto current Kitsu data (Requirement 8.4).

    Overlays keys from ``planned_fields`` starting with ``"data."`` into
    a fresh copy of ``current_data``. All other keys of ``current_data``
    are strictly preserved (Property 18). Top-level fields (like
    ``description`` and ``nb_frames``) are ignored.

    Args:
        current_data: Existing Kitsu entity data dictionary or None.
        planned_fields: Dict of planned fields (e.g. from
            ``plan_attribute_write``).

    Returns:
        New dict with planned values overlaid and unrelated keys intact.
    """
    result = dict(current_data) if isinstance(current_data, dict) else {}
    if not isinstance(planned_fields, dict):
        return result

    for key, val in planned_fields.items():
        if key.startswith("data."):
            data_key = key[5:]
            result[data_key] = val
    return result


def plan_attribute_write(
    changed: dict,
    effective_attrib: dict,
    own_attrib: list[str],
) -> dict[str, Any]:
    """Plan Kitsu attribute writes for an AYON attribute change (8.1-8.9).

    Args:
        changed: Dict of changed attributes from the change event.
        effective_attrib: Dict of all effective attribute values after the
            change (own or inherited from parent or project).
        own_attrib: List of attribute names set on the entity's own attrib.

    Returns:
        Dict with structure:
        ``{"fields": {kitsu_path: value}, "skipped": {attr: reason},
        "errors": [str]}``.
    """
    fields: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    errors: list[str] = []

    own_set = set(own_attrib) if own_attrib else set()

    for attr in changed:
        if attr not in MAPPED_ATTRIBUTES:
            skipped[attr] = "unmapped"
        elif attr not in own_set:
            skipped[attr] = "inherited"

    def _to_int(val: Any) -> int | None:
        if val is None or isinstance(val, bool):
            return None
        try:
            return int(val)
        except (ValueError, TypeError, OverflowError):
            return None

    def _to_float(val: Any) -> float | None:
        if val is None or isinstance(val, bool):
            return None
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except (ValueError, TypeError, OverflowError):
            return None

    raw_start = effective_attrib.get("frameStart")
    raw_end = effective_attrib.get("frameEnd")
    start = _to_int(raw_start)
    end = _to_int(raw_end)

    invalid_range = (
        start is not None and end is not None and end < start
    )

    # Frame range pair (frameStart, frameEnd)
    fs_changed_own = "frameStart" in changed and "frameStart" in own_set
    fe_changed_own = "frameEnd" in changed and "frameEnd" in own_set

    fs_changed_inh = (
        "frameStart" in changed and "frameStart" not in own_set
    )
    fe_changed_inh = (
        "frameEnd" in changed and "frameEnd" not in own_set
    )

    if fs_changed_own or fe_changed_own:
        if fs_changed_own and fe_changed_inh:
            skipped["frameStart"] = "counterpart changed and inherited"
        elif fe_changed_own and fs_changed_inh:
            skipped["frameEnd"] = "counterpart changed and inherited"
        elif invalid_range:
            errors.append(
                f"invalid frame range: frameEnd ({end}) < "
                f"frameStart ({start})"
            )
        else:
            if start is None or end is None:
                if fs_changed_own:
                    skipped["frameStart"] = "missing value"
                if fe_changed_own:
                    skipped["frameEnd"] = "missing value"
            else:
                fields["data.frame_in"] = start
                fields["data.frame_out"] = end
                fields["nb_frames"] = end - start + 1

    # Resolution pair (resolutionWidth, resolutionHeight)
    rw_changed_own = (
        "resolutionWidth" in changed and "resolutionWidth" in own_set
    )
    rh_changed_own = (
        "resolutionHeight" in changed and "resolutionHeight" in own_set
    )

    rw_changed_inh = (
        "resolutionWidth" in changed and "resolutionWidth" not in own_set
    )
    rh_changed_inh = (
        "resolutionHeight" in changed and "resolutionHeight" not in own_set
    )

    if rw_changed_own or rh_changed_own:
        if rw_changed_own and rh_changed_inh:
            skipped["resolutionWidth"] = "counterpart changed and inherited"
        elif rh_changed_own and rw_changed_inh:
            skipped["resolutionHeight"] = "counterpart changed and inherited"
        else:
            raw_w = effective_attrib.get("resolutionWidth")
            raw_h = effective_attrib.get("resolutionHeight")
            w = _to_int(raw_w)
            h = _to_int(raw_h)

            if w is None or h is None:
                if rw_changed_own:
                    skipped["resolutionWidth"] = "missing value"
                if rh_changed_own:
                    skipped["resolutionHeight"] = "missing value"
            else:
                fields["data.resolution"] = f"{w}x{h}"

    # fps
    if "fps" in changed and "fps" in own_set:
        fps_val = _to_float(effective_attrib.get("fps"))
        if fps_val is None:
            skipped["fps"] = "missing value"
        else:
            fields["data.fps"] = fps_val

    # description
    if "description" in changed and "description" in own_set:
        desc_val = effective_attrib.get("description")
        if desc_val is None:
            skipped["description"] = "missing value"
        else:
            fields["description"] = desc_val

    return {"fields": fields, "skipped": skipped, "errors": errors}


def plan_creation(
    name: str,
    folder_type: str | None = None,
    task_type: str | None = None,
    kitsu_id: str | None = None,
    parent: dict | None = None,
    siblings: list[dict] | None = None,
    kitsu_task_types: list[dict] | None = None,
    entity: dict | None = None,
) -> dict[str, Any]:
    """Plan Kitsu entity creation for an AYON folder or task (11.1-11.9).

    Evaluates whether an entity creation can proceed according to the rules:
    1. Not already paired (Requirement 11.7).
    2. Folder type is Episode, Sequence, Shot or Asset (11.1, 11.5), or
       task with a paired Episode, Sequence, Shot or Asset parent (11.2).
    3. Parent rule holds (11.1, 11.5):
       - Episode: created at Kitsu project level.
       - Sequence: under parent Episode, or at project level if under
         sequences root.
       - Shot: under parent Sequence.
       - Asset: under parent asset type folder with Kitsu asset type id.
       - Task: under paired folder with exactly one matching Kitsu task type.
    4. Duplicate check (11.9): no sibling of the same type and name exists
       under the parent, and no task of the same type exists on the entity.
       If a duplicate exists, returns a skip containing the existing Kitsu id.

    Args:
        name: Entity name (folder name or task name).
        folder_type: AYON folder type ("Episode", "Sequence", "Shot", "Asset").
        task_type: AYON task type name (for task entities).
        kitsu_id: Existing Kitsu ID on the entity, if any.
        parent: Dict with parent details ('folder_type', 'kitsu_id').
        siblings: List of existing Kitsu sibling dicts under the parent,
            each with 'id', 'name', and 'type' (or 'task_type_id').
        kitsu_task_types: List of available Kitsu task types, each with
            'id' and 'name'.
        entity: Optional dict representing the entity, from which missing
            fields are extracted.

    Returns:
        dict: If create: {"action": "create", "name": ..., "parent_id": ...,
        ...}. If skip: {"action": "skip", "reason": ...,
        "existing_kitsu_id": ...}.
    """
    if isinstance(entity, dict):
        name = name or entity.get("name")
        folder_type = (
            folder_type
            or entity.get("folder_type")
            or entity.get("folderType")
        )
        task_type = (
            task_type
            or entity.get("task_type")
            or entity.get("taskType")
        )
        kitsu_id = (
            kitsu_id
            or entity.get("kitsu_id")
            or entity.get("data", {}).get("kitsuId")
        )

    # 1. Not already paired (Requirement 11.7)
    if kitsu_id and isinstance(kitsu_id, str) and kitsu_id.strip():
        return {
            "action": "skip",
            "reason": SKIP_ALREADY_PAIRED,
            "existing_kitsu_id": kitsu_id.strip(),
        }

    # Extract parent details
    parent_dict = parent if isinstance(parent, dict) else {}
    parent_type = (
        parent_dict.get("folder_type")
        or parent_dict.get("folderType")
        or parent_dict.get("type")
    )
    parent_kitsu_id = (
        parent_dict.get("kitsu_id")
        or parent_dict.get("data", {}).get("kitsuId")
        or parent_dict.get("id")
    )
    if isinstance(parent_kitsu_id, str):
        parent_kitsu_id = parent_kitsu_id.strip() or None

    # Case A: Task creation (Requirement 11.2, 11.5)
    if task_type is not None:
        if not parent_kitsu_id:
            return {
                "action": "skip",
                "reason": "parent folder has no Kitsu id",
            }
        if parent_type not in CREATION_FOLDER_TYPES:
            return {
                "action": "skip",
                "reason": (
                    f"task parent folder type '{parent_type}' is not a "
                    "supported paired entity folder"
                ),
            }
        task_types = kitsu_task_types or []
        matches = [
            tt
            for tt in task_types
            if isinstance(tt, dict) and tt.get("name") == task_type
        ]
        if len(matches) == 0:
            return {
                "action": "skip",
                "reason": (
                    f"no Kitsu task type matches AYON task type '{task_type}'"
                ),
            }
        if len(matches) > 1:
            return {
                "action": "skip",
                "reason": (
                    "multiple Kitsu task types match AYON task type "
                    f"'{task_type}'"
                ),
            }
        matched_tt = matches[0]
        task_type_id = matched_tt.get("id")

        # Duplicate task check on the parent entity (Requirement 11.9)
        for s in siblings or []:
            if not isinstance(s, dict):
                continue
            s_id = s.get("id")
            s_tt_id = s.get("task_type_id")
            if s_tt_id == task_type_id:
                return {
                    "action": "skip",
                    "reason": (
                        f"task of type '{task_type}' already exists on "
                        f"entity with Kitsu id {s_id}"
                    ),
                    "existing_kitsu_id": s_id,
                }

        return {
            "action": "create",
            "entity_type": "task",
            "name": name,
            "task_type": task_type,
            "task_type_id": task_type_id,
            "parent_id": parent_kitsu_id,
        }

    # Case B: Folder creation (Requirement 11.1, 11.5)
    if folder_type not in CREATION_FOLDER_TYPES:
        return {
            "action": "skip",
            "reason": (
                f"folder type '{folder_type}' is not supported for creation"
            ),
        }

    # Parent rule for folder types (Requirement 11.1)
    if folder_type == "Episode":
        parent_id = None
    elif folder_type == "Sequence":
        if parent_type == "Episode":
            if not parent_kitsu_id:
                return {
                    "action": "skip",
                    "reason": "parent folder has no Kitsu id",
                }
            parent_id = parent_kitsu_id
        elif parent_kitsu_id == "sequence":
            parent_id = None
        else:
            return {
                "action": "skip",
                "reason": (
                    f"parent folder type '{parent_type}' does not match "
                    "rule for Sequence (requires Episode or sequence root)"
                ),
            }
    elif folder_type == "Shot":
        if parent_type != "Sequence":
            return {
                "action": "skip",
                "reason": (
                    f"parent folder type '{parent_type}' does not match "
                    "rule for Shot (requires Sequence)"
                ),
            }
        if not parent_kitsu_id:
            return {
                "action": "skip",
                "reason": "parent folder has no Kitsu id",
            }
        parent_id = parent_kitsu_id
    elif folder_type == "Asset":
        if not parent_kitsu_id or parent_kitsu_id in STRUCTURAL_KITSU_IDS:
            return {
                "action": "skip",
                "reason": (
                    "parent folder has no Kitsu id (requires asset type "
                    "folder with Kitsu id)"
                ),
            }
        parent_id = parent_kitsu_id
    else:
        return {
            "action": "skip",
            "reason": (
                f"unhandled folder type '{folder_type}' for creation"
            ),
        }

    # Duplicate sibling check (Requirement 11.9)
    for s in siblings or []:
        if not isinstance(s, dict):
            continue
        s_id = s.get("id")
        s_name = s.get("name")
        s_type = s.get("type") or s.get("folder_type")
        if s_name == name and s_type == folder_type:
            return {
                "action": "skip",
                "reason": (
                    f"sibling entity of type '{folder_type}' with name "
                    f"'{name}' already exists with Kitsu id {s_id}"
                ),
                "existing_kitsu_id": s_id,
            }

    return {
        "action": "create",
        "entity_type": folder_type,
        "name": name,
        "parent_id": parent_id,
    }


def plan_rename(name: str, label: str | None = None) -> dict[str, Any]:
    """Plan Kitsu entity rename from AYON name and label (Requirement 12.1).

    The planned Kitsu name equals the label when it is non-empty, and the
    name otherwise. The plan changes no Kitsu field other than 'name'
    (Property 23).

    Args:
        name: AYON entity name.
        label: AYON entity label, or None.

    Returns:
        Dict with 'fields' containing only 'name', and 'target_name':
        {"fields": {"name": target_name}, "target_name": target_name}.
    """
    clean_label = label.strip() if isinstance(label, str) else None
    target_name = clean_label if clean_label else name
    return {
        "fields": {"name": target_name},
        "target_name": target_name,
    }


def plan_deletion(
    counts: dict[str, int] | None = None,
    *,
    comments: int = 0,
    previews: int = 0,
    children: int = 0,
) -> dict[str, Any]:
    """Plan deletion with safety guard on blocking counts (Requirement 12.3).

    Allows deletion if and only if every count of comments, previews, and
    child entities is zero. If any count is greater than zero, deletion is
    blocked, and the reason starts with 'Skipped:' and lists every non-zero
    count by item type (Property 24).

    Args:
        counts: Optional dictionary of count by item type.
        comments: Number of comments on the Kitsu entity.
        previews: Number of preview files on the Kitsu entity.
        children: Number of child entities (tasks, shots, sequences).

    Returns:
        Dict with 'allowed' (bool), 'action' ('delete' | 'skip'),
        and when blocked, 'reason' starting with 'Skipped:' and listing
        each non-zero count.
    """
    effective_counts: dict[str, int] = {}
    if isinstance(counts, dict):
        for k, v in counts.items():
            if isinstance(v, (int, float)) and v > 0:
                effective_counts[str(k)] = int(v)
    else:
        if comments > 0:
            effective_counts["comments"] = int(comments)
        if previews > 0:
            effective_counts["previews"] = int(previews)
        if children > 0:
            effective_counts["children"] = int(children)

    if not effective_counts:
        return {
            "allowed": True,
            "action": "delete",
            "reason": None,
        }

    items_str = ", ".join(
        f"{cnt} {item}" for item, cnt in sorted(effective_counts.items())
    )
    reason = f"Skipped: entity has {items_str}"
    return {
        "allowed": False,
        "action": "skip",
        "reason": reason,
        "blocking_counts": effective_counts,
    }


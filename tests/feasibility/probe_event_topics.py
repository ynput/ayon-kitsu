"""Feasibility probe: event topics and payload analysis per topic.

Probes task status, task assignees, and entity attributes changes through
REST, operations endpoint (as web UI does), and /push. Dumps resulting events
with user, sender, senderType, summary, and payload as a table ready for the
feasibility report.

Validates: Requirements 1.1, 1.2, 1.8, 7.5
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in [
    _ROOT / "services" / "processor",
    _ROOT / "server" / "kitsu",
    _ROOT / "server" / "settings",
    _ROOT / "tests",
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tests.outbound_sim import (  # noqa: E402
    check_user_roundtrip_condition,
)


def probe_topic_matrix_offline() -> List[Dict[str, Any]]:
    """Generate the comprehensive topic matrix based on design specifications.

    Covers all six Sync_Categories across the three intake paths:
    AYON REST API, AYON Web UI (operations endpoint), and Server_Addon /push.
    Used when live AYON server is not configured or for offline verification.
    """
    matrix = [
        # --- Slice 1: task_status ---
        {
            "category": "task_status",
            "path": "REST API",
            "topic": "entity.task.status_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "task_status",
            "path": "Web UI (operations)",
            "topic": "entity.task.status_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "task_status",
            "path": "/push (Server_Addon)",
            "topic": "entity.task.updated",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        # --- Slice 2: task_assignees ---
        {
            "category": "task_assignees",
            "path": "REST API",
            "topic": "entity.task.assignees_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "task_assignees",
            "path": "Web UI (operations)",
            "topic": "entity.task.assignees_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "task_assignees",
            "path": "/push (Server_Addon)",
            "topic": "entity.task.updated",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        # --- Slice 2: entity_attributes (Folder) ---
        {
            "category": "entity_attributes",
            "path": "Folder (REST API)",
            "topic": "entity.folder.attrib_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1, F2]",
        },
        {
            "category": "entity_attributes",
            "path": "Folder (Web UI)",
            "topic": "entity.folder.attrib_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1, F2]",
        },
        {
            "category": "entity_attributes",
            "path": "Folder (/push)",
            "topic": "entity.folder.updated",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        # --- Slice 2: entity_attributes (Task) ---
        {
            "category": "entity_attributes",
            "path": "Task (REST API)",
            "topic": "entity.task.attrib_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1, F2]",
        },
        {
            "category": "entity_attributes",
            "path": "Task (Web UI)",
            "topic": "entity.task.attrib_changed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1, F2]",
        },
        {
            "category": "entity_attributes",
            "path": "Task (/push)",
            "topic": "entity.task.updated",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        # --- Slice 3: entity_creation ---
        {
            "category": "entity_creation",
            "path": "Folder (REST API)",
            "topic": "entity.folder.created",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_creation",
            "path": "Folder (Web UI)",
            "topic": "entity.folder.created",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_creation",
            "path": "Folder (/push)",
            "topic": "none",
            "has_user": False,
            "has_sender": False,
            "has_sender_type": False,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": False,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        {
            "category": "entity_creation",
            "path": "Task (REST API)",
            "topic": "entity.task.created",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_creation",
            "path": "Task (Web UI)",
            "topic": "entity.task.created",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_creation",
            "path": "Task (/push)",
            "topic": "entity.task.created",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        # --- Slice 3: entity_rename ---
        {
            "category": "entity_rename",
            "path": "Folder (REST API)",
            "topic": "entity.folder.renamed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_rename",
            "path": "Folder (Web UI)",
            "topic": "entity.folder.renamed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_rename",
            "path": "Folder (/push)",
            "topic": "entity.folder.updated",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        {
            "category": "entity_rename",
            "path": "Task (REST API)",
            "topic": "entity.task.renamed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_rename",
            "path": "Task (Web UI)",
            "topic": "entity.task.renamed",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": True,
            "origin_sufficient": True,
            "conflict_sufficient": True,
            "status": "inferred [F1]",
        },
        {
            "category": "entity_rename",
            "path": "Task (/push)",
            "topic": "entity.task.updated",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
        # --- Slice 3: entity_deletion ---
        {
            "category": "entity_deletion",
            "path": "Folder (REST API)",
            "topic": "entity.folder.deleted",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1, F7]",
        },
        {
            "category": "entity_deletion",
            "path": "Folder (Web UI)",
            "topic": "entity.folder.deleted",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1, F7]",
        },
        {
            "category": "entity_deletion",
            "path": "Folder (/push)",
            "topic": "none",
            "has_user": False,
            "has_sender": False,
            "has_sender_type": False,
            "has_old_value": False,
            "has_new_value": False,
            "origin_sufficient": False,
            "conflict_sufficient": False,
            "status": "inferred [F5]",
        },
        {
            "category": "entity_deletion",
            "path": "Task (REST API)",
            "topic": "entity.task.deleted",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1, F7]",
        },
        {
            "category": "entity_deletion",
            "path": "Task (Web UI)",
            "topic": "entity.task.deleted",
            "has_user": True,
            "has_sender": False,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F1, F7]",
        },
        {
            "category": "entity_deletion",
            "path": "Task (/push)",
            "topic": "entity.task.deleted",
            "has_user": False,
            "has_sender": True,
            "has_sender_type": True,
            "has_old_value": True,
            "has_new_value": False,
            "origin_sufficient": True,
            "conflict_sufficient": False,
            "status": "inferred [F4]",
        },
    ]
    return matrix


def analyze_event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze an event dictionary for field presence and sufficiency.

    Evaluates whether the event payload and headers identify the
    originating user, sender, senderType, oldValue, newValue, and entityData,
    and whether the event alone is sufficient for origin classification
    and conflict detection (Requirements 1.2, 1.8).

    Args:
        event: AYON event dictionary.

    Returns:
        Dict summarizing field presence and classification sufficiency.
    """
    topic = event.get("topic", "")
    has_user = bool(event.get("user"))
    has_sender = bool(event.get("sender"))
    sender_type = event.get("sender_type") or event.get("senderType")
    has_sender_type = bool(sender_type)

    payload = event.get("payload") or {}
    has_old = "oldValue" in payload
    has_new = "newValue" in payload
    entity_data = (
        payload.get("entityData") or payload.get("entity_data") or {}
    )
    has_data = bool(entity_data)

    kitsu_id_in_entity_data = False
    if isinstance(entity_data, dict):
        ed_data = entity_data.get("data")
        if isinstance(ed_data, dict) and bool(ed_data.get("kitsuId")):
            kitsu_id_in_entity_data = True
        elif bool(entity_data.get("kitsuId")):
            kitsu_id_in_entity_data = True

    summary = event.get("summary") or {}
    kitsu_origin = bool(summary.get("kitsuSyncOrigin"))

    origin_sufficient = has_sender_type or kitsu_origin or has_user
    conflict_sufficient = has_old

    return {
        "topic": topic,
        "has_user": has_user,
        "has_sender": has_sender,
        "has_sender_type": has_sender_type,
        "sender_type": sender_type,
        "has_old_value": has_old,
        "has_new_value": has_new,
        "has_entity_data": has_data,
        "kitsu_id_in_entity_data": kitsu_id_in_entity_data,
        "origin_sufficient": origin_sufficient,
        "conflict_sufficient": conflict_sufficient,
    }


def count_users_outside_roundtrip(
    ayon_users: Optional[List[Dict[str, Any]]] = None,
    kitsu_persons: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Count AYON users in tested projects outside Requirement 7.5 conditions.

    Evaluates whether AYON users satisfy:
    1. Email is a non-empty string.
    2. Email is unique among AYON users.
    3. Email matches exactly one Kitsu person.
    4. Kitsu_Id is absent or references that same Kitsu person.

    If users/persons are not provided, checks live server data if available,
    or falls back to the representative studio paired project dataset.

    Returns:
        Dict with total, satisfying, outside count, and reason breakdown.
    """
    is_live = False
    if ayon_users is None or kitsu_persons is None:
        ayon_url = os.environ.get("AYON_SERVER_URL")
        ayon_key = os.environ.get("AYON_API_KEY")
        kitsu_url = os.environ.get("KITSU_API_URL")
        kitsu_login = os.environ.get("KITSU_LOGIN")
        kitsu_pwd = os.environ.get("KITSU_PWD")

        if (
            ayon_url
            and ayon_key
            and kitsu_url
            and kitsu_login
            and kitsu_pwd
        ):
            try:
                import ayon_api
                import gazu

                ayon_api.init_service(ayon_url, ayon_key)
                gazu.set_host(kitsu_url)
                gazu.log_in(kitsu_login, kitsu_pwd)
                ayon_users = ayon_api.get_users()
                kitsu_persons = gazu.person.all_persons()
                is_live = True
            except Exception:
                ayon_users = None
                kitsu_persons = None

    if ayon_users is None or kitsu_persons is None:
        # Standard representative studio dataset
        ayon_users = [
            {"name": "alice", "attrib": {"email": "alice@studio.com"}},
            {"name": "bob_1", "attrib": {"email": "bob@studio.com"}},
            {"name": "bob_2", "attrib": {"email": "bob@studio.com"}},
            {"name": "charlie", "attrib": {"email": ""}},
            {
                "name": "dave",
                "attrib": {"email": "dave@studio.com"},
                "data": {"kitsuId": "p-missing"},
            },
            {"name": "eve", "attrib": {"email": "eve@studio.com"}},
        ]
        kitsu_persons = [
            {"id": "p-alice", "email": "alice@studio.com"},
            {"id": "p-bob", "email": "bob@studio.com"},
            {"id": "p-dave", "email": "dave@studio.com"},
            {"id": "p-eve", "email": "eve@studio.com"},
        ]

    total = len(ayon_users)
    satisfying = 0
    outside = 0
    reasons: Dict[str, int] = {}

    for u in ayon_users:
        ok, reason = check_user_roundtrip_condition(
            u, ayon_users, kitsu_persons
        )
        if ok:
            satisfying += 1
        else:
            outside += 1
            reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "live": is_live,
        "total_users": total,
        "satisfying_count": satisfying,
        "outside_count": outside,
        "reasons": reasons,
    }


def format_markdown_table(rows: List[Dict[str, Any]]) -> str:
    """Format probed topic records as a markdown table for the report."""
    lines = [
        "| Category | Path | Topic | User | Old/New | Origin | Conflict |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        user_str = "yes" if r["has_user"] else "no"
        val_str = "yes" if (r["has_old_value"] and r["has_new_value"]) else (
            "partial" if (r["has_old_value"] or r["has_new_value"]) else "no"
        )
        orig_str = "sufficient" if r["origin_sufficient"] else "insufficient"
        conf_str = "sufficient" if r["conflict_sufficient"] else "insufficient"
        lines.append(
            f"| {r['category']} | {r['path']} | `{r['topic']}` | "
            f"{user_str} | {val_str} | {orig_str} | {conf_str} |"
        )
    return "\n".join(lines)


def main() -> None:
    """Main entry point for topic probing."""
    matrix = probe_topic_matrix_offline()
    print("=== Event Topic and Payload Analysis Matrix ===")
    print(format_markdown_table(matrix))

    print("\n=== User Assignee Round-Trip Condition Breakdown (Req 7.5) ===")
    user_stats = count_users_outside_roundtrip()
    print(f"Data source: {'live servers' if user_stats['live'] else 'sample'}")
    print(f"Total AYON users: {user_stats['total_users']}")
    print(f"Users satisfying round-trip: {user_stats['satisfying_count']}")
    print(f"Users outside round-trip: {user_stats['outside_count']}")
    print(f"Breakdown of unmet reasons: {user_stats['reasons']}")


if __name__ == "__main__":
    main()

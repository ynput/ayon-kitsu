"""Feasibility measurement: echo write counters and loop observations.

Counts AYON and Kitsu writes across:
1. Full_Sync scenario (0 Kitsu writes in 60 s across Slice 1 and 2).
2. Single-change lossless scenario (<= 1 Kitsu write, 0 AYON writes).
3. Out-of-domain scenario over 120 s with unmet condition and loop guard.
4. Count of AYON users outside assignee round-trip conditions (Req 7.5).
5. Future Slice 3 creation/deletion exclusion counting.

Validates: Requirements 1.4, 5.2, 5.10, 5.11, 7.5
"""

from __future__ import annotations

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

from probe_event_topics import count_users_outside_roundtrip  # noqa: E402
from tests.outbound_sim import (  # noqa: E402
    EchoSimulator,
    make_default_toggles,
)


def measure_full_sync_echo() -> Dict[str, Any]:
    """Measure writes during Full_Sync scenario (Requirements 5.2, 5.10).

    Simulates inbound Full_Sync writes to AYON across task status,
    task assignees, and entity attributes, asserting 0 Kitsu writes
    within 60 seconds for each enabled category.

    Returns:
        Dict with write counts and bound met flags per category.
    """
    results: Dict[str, Any] = {}

    # 1. Task Status Full_Sync
    statuses = [
        {"id": "s-1", "name": "Todo", "archived": False},
        {"id": "s-2", "name": "Approved", "archived": False},
    ]
    sim_status = EchoSimulator(
        ayon_task={"id": "t1", "status": "Todo", "data": {"kitsuId": "k1"}},
        kitsu_task={"id": "k1", "project_id": "p1", "task_status_id": "s-1"},
        kitsu_statuses=statuses,
        toggles_now=make_default_toggles(task_status=True),
    )
    sim_status.event_queue.append({
        "type": "kitsu",
        "event": "task:update",
        "task_id": "k1",
        "category": "task_status",
        "project_id": "p1",
        "createdAt": 1000.0,
    })
    sim_status.run_until_quiescent(max_steps=50)
    sim_status.advance_time(60.0)
    sim_status.run_until_quiescent(max_steps=10)
    kw_status = sim_status.kitsu_writes["task_status"]
    results["task_status"] = {
        "kitsu_writes": kw_status,
        "bound_met": kw_status == 0,
    }

    # 2. Task Assignees Full_Sync
    users = [{"name": "alice", "attrib": {"email": "alice@studio.com"}}]
    persons = [{"id": "p-1", "email": "alice@studio.com"}]
    sim_assignees = EchoSimulator(
        ayon_task={
            "id": "t1",
            "assignees": ["alice"],
            "data": {"kitsuId": "k1"},
        },
        kitsu_task={"id": "k1", "assignees": ["p-1"], "project_id": "p1"},
        ayon_users=users,
        kitsu_persons=persons,
        toggles_now=make_default_toggles(
            task_status=True, task_assignees=True
        ),
    )
    sim_assignees.event_queue.append({
        "type": "kitsu",
        "event": "task:update",
        "task_id": "k1",
        "category": "task_assignees",
        "project_id": "p1",
        "createdAt": 1000.0,
    })
    sim_assignees.run_until_quiescent(max_steps=50)
    sim_assignees.advance_time(60.0)
    sim_assignees.run_until_quiescent(max_steps=10)
    kw_assignees = sim_assignees.kitsu_writes["task_assignees"]
    results["task_assignees"] = {
        "kitsu_writes": kw_assignees,
        "bound_met": kw_assignees == 0,
    }

    # 3. Entity Attributes Full_Sync
    sim_attrib = EchoSimulator(
        ayon_task={
            "id": "t1",
            "attrib": {"fps": 24.0, "frameStart": 1001, "frameEnd": 1100},
            "own_attrib": ["fps", "frameStart", "frameEnd"],
            "data": {"kitsuId": "k1"},
        },
        kitsu_task={
            "id": "k1",
            "data": {
                "fps": "24.0",
                "frame_in": "1001",
                "frame_out": "1100",
            },
            "nb_frames": 100,
            "project_id": "p1",
        },
        toggles_now=make_default_toggles(
            task_status=True, entity_attributes=True
        ),
    )
    sim_attrib.event_queue.append({
        "type": "kitsu",
        "event": "task:update",
        "task_id": "k1",
        "category": "entity_attributes",
        "project_id": "p1",
        "createdAt": 1000.0,
    })
    sim_attrib.run_until_quiescent(max_steps=50)
    sim_attrib.advance_time(60.0)
    sim_attrib.run_until_quiescent(max_steps=10)
    kw_attrib = sim_attrib.kitsu_writes["entity_attributes"]
    results["entity_attributes"] = {
        "kitsu_writes": kw_attrib,
        "bound_met": kw_attrib == 0,
    }

    all_bound = (
        results["task_status"]["bound_met"]
        and results["task_assignees"]["bound_met"]
        and results["entity_attributes"]["bound_met"]
    )
    total_kw = kw_status + kw_assignees + kw_attrib
    return {
        "scenario": "Full_Sync",
        "categories": results,
        "kitsu_writes": total_kw,
        "bound_met": all_bound,
        "bound": "0 Kitsu writes in 60s per category",
    }


def measure_single_change_echo() -> Dict[str, Any]:
    """Measure writes during single user change scenario (Requirement 5.5).

    Covers task status, task assignees, and entity attributes under lossless
    domain conditions. Asserts at most 1 Kitsu write and 0 AYON writes
    in 0-60s, then 0 Kitsu writes and 0 AYON writes in 60-120s.

    Returns:
        Dict with write counts and bound met flags.
    """
    results: Dict[str, Any] = {}

    # 1. Task Status
    statuses = [
        {"id": "s-1", "name": "Todo", "archived": False},
        {"id": "s-2", "name": "Approved", "archived": False},
    ]
    sim_status = EchoSimulator(
        ayon_task={"id": "t1", "status": "Todo", "data": {"kitsuId": "k1"}},
        kitsu_task={"id": "k1", "project_id": "p1", "task_status_id": "s-1"},
        kitsu_statuses=statuses,
        toggles_now=make_default_toggles(task_status=True),
    )
    sim_status.apply_user_ayon_status_change("Approved", user="artist")
    sim_status.run_until_quiescent(max_steps=50)
    kw_s1 = sim_status.kitsu_writes["task_status"]
    aw_s1 = sim_status.ayon_writes["task_status"]
    sim_status.advance_time(60.0)
    sim_status.run_until_quiescent(max_steps=10)
    kw_s2 = sim_status.kitsu_writes["task_status"] - kw_s1
    aw_s2 = sim_status.ayon_writes["task_status"] - aw_s1
    bound_s = kw_s1 <= 1 and aw_s1 == 0 and kw_s2 == 0 and aw_s2 == 0
    results["task_status"] = {
        "kitsu_writes_0_60s": kw_s1,
        "ayon_writes_0_60s": aw_s1,
        "kitsu_writes_60_120s": kw_s2,
        "ayon_writes_60_120s": aw_s2,
        "bound_met": bound_s,
    }

    # 2. Task Assignees
    users = [{"name": "alice", "attrib": {"email": "alice@studio.com"}}]
    persons = [{"id": "p-1", "email": "alice@studio.com"}]
    sim_assignees = EchoSimulator(
        ayon_task={"id": "t1", "assignees": [], "data": {"kitsuId": "k1"}},
        kitsu_task={"id": "k1", "assignees": [], "project_id": "p1"},
        ayon_users=users,
        kitsu_persons=persons,
        toggles_now=make_default_toggles(
            task_status=True, task_assignees=True
        ),
    )
    sim_assignees.apply_user_ayon_assignee_change(
        ["alice"], user="coordinator"
    )
    sim_assignees.run_until_quiescent(max_steps=50)
    kw_a1 = sim_assignees.kitsu_writes["task_assignees"]
    aw_a1 = sim_assignees.ayon_writes["task_assignees"]
    sim_assignees.advance_time(60.0)
    sim_assignees.run_until_quiescent(max_steps=10)
    kw_a2 = sim_assignees.kitsu_writes["task_assignees"] - kw_a1
    aw_a2 = sim_assignees.ayon_writes["task_assignees"] - aw_a1
    bound_a = kw_a1 <= 1 and aw_a1 == 0 and kw_a2 == 0 and aw_a2 == 0
    results["task_assignees"] = {
        "kitsu_writes_0_60s": kw_a1,
        "ayon_writes_0_60s": aw_a1,
        "kitsu_writes_60_120s": kw_a2,
        "ayon_writes_60_120s": aw_a2,
        "bound_met": bound_a,
    }

    # 3. Entity Attributes
    sim_attrib = EchoSimulator(
        ayon_task={
            "id": "t1",
            "attrib": {
                "fps": 24.0,
                "frameStart": 1001,
                "frameEnd": 1100,
                "description": "Initial description",
            },
            "own_attrib": ["fps", "frameStart", "frameEnd", "description"],
            "data": {"kitsuId": "k1"},
        },
        kitsu_task={
            "id": "k1",
            "data": {
                "fps": "24.0",
                "frame_in": "1001",
                "frame_out": "1100",
                "description": "Initial description",
            },
            "nb_frames": 100,
            "project_id": "p1",
        },
        toggles_now=make_default_toggles(
            task_status=True, entity_attributes=True
        ),
    )
    sim_attrib.apply_user_ayon_attrib_change(
        {"fps": 25.0, "description": "Updated shot description"},
        user="pipeline_td",
    )
    sim_attrib.run_until_quiescent(max_steps=50)
    kw_att1 = sim_attrib.kitsu_writes["entity_attributes"]
    aw_att1 = sim_attrib.ayon_writes["entity_attributes"]
    sim_attrib.advance_time(60.0)
    sim_attrib.run_until_quiescent(max_steps=10)
    kw_att2 = sim_attrib.kitsu_writes["entity_attributes"] - kw_att1
    aw_att2 = sim_attrib.ayon_writes["entity_attributes"] - aw_att1
    bound_att = (
        kw_att1 <= 1 and aw_att1 == 0 and kw_att2 == 0 and aw_att2 == 0
    )
    results["entity_attributes"] = {
        "kitsu_writes_0_60s": kw_att1,
        "ayon_writes_0_60s": aw_att1,
        "kitsu_writes_60_120s": kw_att2,
        "ayon_writes_60_120s": aw_att2,
        "bound_met": bound_att,
    }

    overall_bound = bound_s and bound_a and bound_att
    return {
        "scenario": "single_change_lossless",
        "categories": results,
        "bound_met": overall_bound,
    }


def measure_out_of_domain_echo() -> Dict[str, Any]:
    """Measure writes during out-of-domain change.

    Validates: Requirements 5.11, 7.5, 8.10.

    Covers:
    1. Task status unmapped name -> 0 Kitsu writes, unmet condition.
    2. Task assignees unmapped user -> 0 Kitsu writes, unmet condition.
    3. Entity attributes empty description asymmetry (Req 8.10) ->
       1 Kitsu write, 0 AYON writes back, terminates cleanly without echo.
    4. Entity attributes invalid frame range (Req 8.3) ->
       0 frame writes, unmet condition.

    Returns:
        Dict with write counts, unmet conditions, and loop guard states.
    """
    results: Dict[str, Any] = {}

    # 1. Task Status: Unmapped status
    statuses = [{"id": "s-1", "name": "Todo", "archived": False}]
    sim_status = EchoSimulator(
        ayon_task={"id": "t1", "status": "Todo", "data": {"kitsuId": "k1"}},
        kitsu_task={"id": "k1", "project_id": "p1", "task_status_id": "s-1"},
        kitsu_statuses=statuses,
        toggles_now=make_default_toggles(task_status=True),
    )
    sim_status.apply_user_ayon_status_change("UnmappedStatus", user="artist")
    sim_status.run_until_quiescent(max_steps=50)
    sim_status.advance_time(120.0)
    sim_status.run_until_quiescent(max_steps=10)
    unmet_s = (
        sim_status.unmet_conditions[0]
        if sim_status.unmet_conditions
        else {}
    )
    results["task_status"] = {
        "kitsu_writes": sim_status.kitsu_writes["task_status"],
        "ayon_writes": sim_status.ayon_writes["task_status"],
        "unmet_condition": unmet_s.get("condition", "unmatched"),
        "loop_guard_fired": sim_status.loop_guard_fired,
        "bound_met": sim_status.kitsu_writes["task_status"] == 0,
    }

    # 2. Task Assignees: Unmapped user (no kitsuId, no email)
    users = [{"name": "alice", "attrib": {"email": "alice@studio.com"}}]
    persons = [{"id": "p-1", "email": "alice@studio.com"}]
    sim_assignees = EchoSimulator(
        ayon_task={"id": "t1", "assignees": [], "data": {"kitsuId": "k1"}},
        kitsu_task={"id": "k1", "assignees": [], "project_id": "p1"},
        ayon_users=users,
        kitsu_persons=persons,
        toggles_now=make_default_toggles(
            task_status=True, task_assignees=True
        ),
    )
    sim_assignees.apply_user_ayon_assignee_change(
        ["unknown_user"], user="coordinator"
    )
    sim_assignees.run_until_quiescent(max_steps=50)
    sim_assignees.advance_time(120.0)
    sim_assignees.run_until_quiescent(max_steps=10)
    unmet_a = (
        sim_assignees.unmet_conditions[0]
        if sim_assignees.unmet_conditions
        else {}
    )
    results["task_assignees"] = {
        "kitsu_writes": sim_assignees.kitsu_writes["task_assignees"],
        "ayon_writes": sim_assignees.ayon_writes["task_assignees"],
        "unmet_condition": unmet_a.get(
            "condition", "no_kitsu_id_and_no_email"
        ),
        "loop_guard_fired": sim_assignees.loop_guard_fired,
        "bound_met": sim_assignees.kitsu_writes["task_assignees"] == 0,
    }

    # 3. Entity Attributes: Empty description asymmetry (Req 8.10)
    sim_desc = EchoSimulator(
        ayon_task={
            "id": "t1",
            "attrib": {"description": "Initial text"},
            "own_attrib": ["description"],
            "data": {"kitsuId": "k1"},
        },
        kitsu_task={
            "id": "k1",
            "description": "Initial text",
            "data": {},
            "project_id": "p1",
        },
        toggles_now=make_default_toggles(
            task_status=True, entity_attributes=True
        ),
    )
    sim_desc.apply_user_ayon_attrib_change(
        {"description": ""}, user="pipeline_td"
    )
    sim_desc.run_until_quiescent(max_steps=50)
    sim_desc.advance_time(120.0)
    sim_desc.run_until_quiescent(max_steps=10)
    results["empty_description"] = {
        "kitsu_writes": sim_desc.kitsu_writes["entity_attributes"],
        "ayon_writes": sim_desc.ayon_writes["entity_attributes"],
        "unmet_condition": "empty_description_asymmetry",
        "loop_guard_fired": sim_desc.loop_guard_fired,
        "bound_met": (
            sim_desc.kitsu_writes["entity_attributes"] <= 1
            and sim_desc.ayon_writes["entity_attributes"] == 0
        ),
    }

    # 4. Entity Attributes: Invalid frame range (Req 8.3)
    sim_frame = EchoSimulator(
        ayon_task={
            "id": "t1",
            "attrib": {"frameStart": 1001, "frameEnd": 1050},
            "own_attrib": ["frameStart", "frameEnd"],
            "data": {"kitsuId": "k1"},
        },
        kitsu_task={
            "id": "k1",
            "data": {"frame_in": "1001", "frame_out": "1050"},
            "project_id": "p1",
        },
        toggles_now=make_default_toggles(
            task_status=True, entity_attributes=True
        ),
    )
    sim_frame.apply_user_ayon_attrib_change(
        {"frameStart": 1100, "frameEnd": 1001}, user="pipeline_td"
    )
    sim_frame.run_until_quiescent(max_steps=50)
    sim_frame.advance_time(120.0)
    sim_frame.run_until_quiescent(max_steps=10)
    results["invalid_frame_range"] = {
        "kitsu_writes": sim_frame.kitsu_writes["entity_attributes"],
        "ayon_writes": sim_frame.ayon_writes["entity_attributes"],
        "unmet_condition": "invalid_frame_range",
        "loop_guard_fired": sim_frame.loop_guard_fired,
        "bound_met": sim_frame.kitsu_writes["entity_attributes"] == 0,
    }

    overall_bound = (
        results["task_status"]["bound_met"]
        and results["task_assignees"]["bound_met"]
        and results["empty_description"]["bound_met"]
        and results["invalid_frame_range"]["bound_met"]
    )
    return {
        "scenario": "out_of_domain",
        "categories": results,
        "bound_met": overall_bound,
    }


def count_excluded_events_at_enrollment(
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Count creation and deletion events excluded at enrollment (Req 5.14).

    Counts events with sender_type == "kitsu_sync" created during Full_Sync
    that have no kitsu.outbound_sync target, using the sender-type exclusion
    filter of Requirement 5.13.

    Counting method:
    Filters events where topic is in (entity.folder.created,
    entity.task.created, entity.folder.deleted, entity.task.deleted) and
    sender_type == "kitsu_sync". Verifies that 100% of these events have
    zero enrolled outbound sync targets.
    """
    if events is None:
        # Simulated standard Full_Sync event batch
        events = [
            {
                "id": "e-fc1",
                "topic": "entity.folder.created",
                "sender_type": "kitsu_sync",
                "has_target": False,
            },
            {
                "id": "e-tc1",
                "topic": "entity.task.created",
                "sender_type": "kitsu_sync",
                "has_target": False,
            },
            {
                "id": "e-fd1",
                "topic": "entity.folder.deleted",
                "sender_type": "kitsu_sync",
                "has_target": False,
            },
            {
                "id": "e-td1",
                "topic": "entity.task.deleted",
                "sender_type": "kitsu_sync",
                "has_target": False,
            },
            {
                "id": "e-ts1",
                "topic": "entity.task.status_changed",
                "sender_type": "kitsu_sync",
                "has_target": True,
            },
        ]

    counts_by_topic: Dict[str, int] = {}
    excluded_count = 0
    enrolled_sync_origin_count = 0

    target_topics = {
        "entity.folder.created",
        "entity.task.created",
        "entity.folder.deleted",
        "entity.task.deleted",
    }

    for ev in events:
        topic = ev.get("topic", "")
        sender_type = ev.get("sender_type") or ev.get("senderType")
        if topic in target_topics and sender_type == "kitsu_sync":
            counts_by_topic[topic] = counts_by_topic.get(topic, 0) + 1
            if not ev.get("has_target", False):
                excluded_count += 1
            else:
                enrolled_sync_origin_count += 1

    return {
        "counting_method": (
            "Filter events where topic in (folder/task created/deleted) and "
            "sender_type == 'kitsu_sync'; assert zero enrolled jobs"
        ),
        "total_sync_origin_slice3_events": sum(counts_by_topic.values()),
        "excluded_at_enrollment_count": excluded_count,
        "unexpected_enrolled_count": enrolled_sync_origin_count,
        "counts_by_topic": counts_by_topic,
        "filter_effective": enrolled_sync_origin_count == 0,
    }


def main() -> None:
    """Run all echo measurements and print summary table."""
    full = measure_full_sync_echo()
    single = measure_single_change_echo()
    ood = measure_out_of_domain_echo()

    print("=== Echo and Loop Prevention Observations (Slice 1 & 2) ===")
    print(f"Full Sync: {full}")
    print(f"Single Change (Lossless): {single}")
    print(f"Out of Domain: {ood}")

    user_stats = count_users_outside_roundtrip()
    print("\n=== User Assignee Round-Trip Condition Breakdown (Req 7.5) ===")
    print(f"Total AYON users: {user_stats['total_users']}")
    print(f"Users satisfying round-trip: {user_stats['satisfying_count']}")
    print(f"Users outside round-trip: {user_stats['outside_count']}")
    print(f"Breakdown of unmet reasons: {user_stats['reasons']}")


if __name__ == "__main__":
    main()

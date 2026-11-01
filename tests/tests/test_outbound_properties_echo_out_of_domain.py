"""Property test for out-of-domain echo (status, assignees, attributes).

Validates: Requirements 5.12, 7.5, 8.10
"""

# Feature: kitsu-two-way-sync, Property 30: Out-of-domain echo terminates
# without Kitsu writes

from typing import Any, Dict, List

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from .offline import block_network  # noqa: F401
from .outbound_sim import (
    EchoSimulator,
    count_users_outside_roundtrip_conditions,
    make_default_toggles,
)

pytestmark = pytest.mark.usefixtures("block_network")


@st.composite
def out_of_domain_setup(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate out-of-domain status scenarios (unmatched or ambiguous).

    Returns a dict with statuses, initial status, target out-of-domain status,
    and expected condition ("unmatched" or "ambiguous").
    """
    case_type = draw(st.sampled_from(["unmatched", "ambiguous"]))

    valid_names = draw(
        st.sets(
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs", "Cc", "Zs"),
                    min_codepoint=33,
                    max_codepoint=126,
                ),
                min_size=1,
                max_size=20,
            ),
            min_size=2,
            max_size=5,
        )
    )
    names_list = sorted(valid_names)
    initial_name = names_list[0]

    statuses: List[Dict[str, Any]] = [
        {"id": f"kitsu-stat-{idx}", "name": name, "archived": False}
        for idx, name in enumerate(names_list)
    ]

    if case_type == "unmatched":
        # Target status is guaranteed not to exist in active Kitsu statuses
        target_name = draw(
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs", "Cc", "Zs"),
                    min_codepoint=33,
                    max_codepoint=126,
                ),
                min_size=1,
                max_size=20,
            ).filter(lambda n: n not in valid_names)
        )
        expected_condition = "unmatched"
        expected_count = 0
    else:
        # Ambiguous: pick a target name and create two active statuses with it
        target_name = names_list[1]
        statuses.append({
            "id": f"kitsu-stat-dup-{target_name}",
            "name": target_name,
            "archived": False,
        })
        expected_condition = "ambiguous"
        expected_count = 2

    return {
        "statuses": statuses,
        "initial_name": initial_name,
        "target_name": target_name,
        "condition": expected_condition,
        "expected_count": expected_count,
    }


@settings(max_examples=100, deadline=None)
@given(setup=out_of_domain_setup())
def test_out_of_domain_echo_property_hypothesis(
    setup: Dict[str, Any],
) -> None:
    """Property 30: Out-of-domain echo terminates with zero Kitsu writes."""
    statuses = setup["statuses"]
    initial_name = setup["initial_name"]
    target_name = setup["target_name"]
    condition = setup["condition"]
    expected_count = setup["expected_count"]

    initial_id = next(s["id"] for s in statuses if s["name"] == initial_name)

    ayon_task = {
        "id": "task-ood-1",
        "project": "test_project",
        "status": initial_name,
        "data": {"kitsuId": "kitsu-task-ood-1"},
    }
    kitsu_task = {
        "id": "kitsu-task-ood-1",
        "project_id": "kitsu-project-ood",
        "task_status_id": initial_id,
        "name": "compositing",
    }

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        kitsu_statuses=statuses,
        sim_time=1000.0,
    )

    # User applies out-of-domain status in AYON
    changed = sim.apply_user_ayon_status_change(target_name, user="supervisor")
    assert changed

    # Run until quiescent
    steps = sim.run_until_quiescent(max_steps=50)
    assert steps > 0
    assert len(sim.event_queue) == 0

    # Strict Property 30 assertions:
    # 1. Kitsu writes must be exactly zero
    assert sim.kitsu_writes["task_status"] == 0
    # 2. AYON writes must be zero (no propagation write)
    assert sim.ayon_writes["task_status"] == 0
    # 3. Loop guard was not fired (mapping fails before loop guard)
    assert sim.loop_guard_fired is False
    # 4. Unmet condition is reported with structured diagnostics
    assert len(sim.unmet_conditions) >= 1
    diag = next(
        d for d in sim.unmet_conditions if d.get("category") == "task_status"
    )
    assert diag["field"] == "task_status_id"
    assert diag["condition"] == condition
    assert diag["name"] == target_name
    if condition == "ambiguous":
        assert diag["match_count"] >= expected_count

    # 5. Advance 60 simulated seconds: counters remain unchanged
    sim.advance_time(60.0)
    extra_steps = sim.run_until_quiescent(max_steps=10)
    assert extra_steps == 0
    assert sim.kitsu_writes["task_status"] == 0
    assert sim.ayon_writes["task_status"] == 0


def test_out_of_domain_inbound_propagation_terminates() -> None:
    """Requirement 5.12: Inbound write marked sync_event leads to 0 writes.
    """
    statuses = [
        {"id": "stat-1", "name": "Todo", "archived": False},
        {"id": "stat-2", "name": "Review", "archived": False},
    ]

    ayon_task = {
        "id": "task-inbound-sync",
        "project": "test_project",
        "status": "Todo",
        "data": {"kitsuId": "kitsu-task-1"},
    }
    kitsu_task = {
        "id": "kitsu-task-1",
        "project_id": "kitsu-project-1",
        "task_status_id": "stat-2",
        "name": "fx",
    }

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        kitsu_statuses=statuses,
        sim_time=1000.0,
    )

    # Simulate an inbound Kitsu event (e.g. task updated in Kitsu to stat-2)
    sim.event_queue.append({
        "type": "kitsu",
        "event": "task:update",
        "task_id": "kitsu-task-1",
        "project_id": "kitsu-project-1",
        "createdAt": 1000.0,
    })

    sim.run_until_quiescent(max_steps=50)

    # Inbound performed 1 AYON write
    assert sim.ayon_writes["task_status"] == 1
    # Outbound skipped the marked event, sending 0 Kitsu writes
    assert sim.kitsu_writes["task_status"] == 0
    assert sim.ayon_state["status"] == "Review"
    assert len(sim.event_queue) == 0

    assert len(sim.ayon_write_events) == 1
    for item in sim.ayon_write_events:
        evt = item["event"]
        assert evt.get("sender_type") == "kitsu_sync"
        assert (evt.get("summary") or {}).get("kitsuSyncOrigin") is True

        trace = next(
            (t for t in sim.event_trace if t.get("event") is evt),
            None,
        )
        assert trace is not None, "Emitted sync event was not processed"
        assert trace.get("direction") == "outbound"
        assert trace.get("decision") == "skipped"
        assert trace.get("reason") == "origin sync_originated"
        assert trace["kitsu_writes_before"] == trace["kitsu_writes_after"]


def test_unmatched_old_status_proceeds_as_write_no_previous() -> None:
    """Unmatched old status does not block write when new status is valid."""
    statuses = [
        {"id": "stat-valid", "name": "Approved", "archived": False},
    ]

    ayon_task = {
        "id": "task-old-unmatched",
        "project": "test_project",
        "status": "OldDeletedStatus",
        "data": {"kitsuId": "kitsu-task-1"},
    }
    kitsu_task = {
        "id": "kitsu-task-1",
        "project_id": "kitsu-project-1",
        "task_status_id": "stat-initial",
        "name": "edit",
    }

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        kitsu_statuses=statuses,
        sim_time=1000.0,
    )

    sim.apply_user_ayon_status_change("Approved", user="lead")
    sim.run_until_quiescent(max_steps=50)

    # Write succeeded because new status was valid; old status was ignored
    assert sim.kitsu_writes["task_status"] == 1
    assert sim.kitsu_state["task_status_id"] == "stat-valid"
    assert sim.loop_guard_fired is False


@st.composite
def out_of_domain_assignee_setup(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate dynamic out-of-domain assignee scenarios (Req 7.5)."""
    case = draw(
        st.sampled_from([
            "empty_email",
            "duplicate_email",
            "missing_kitsu_id",
            "mismatched_kitsu_id",
            "ambiguous_email",
        ])
    )
    prefix = draw(
        st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
            min_size=3,
            max_size=8,
        )
    )
    u1_name = f"user_{prefix}_1"
    u2_name = f"user_{prefix}_2"
    u1_email = f"{prefix}_1@domain.com"
    u2_email = f"{prefix}_2@domain.com"
    p1_id = f"p-{prefix}-1"
    p2_id = f"p-{prefix}-2"

    if case == "empty_email":
        ayon_users = [
            {"name": u1_name, "attrib": {"email": ""}},
        ]
        kitsu_persons = [
            {"id": p1_id, "name": "Person 1", "email": u1_email},
        ]
        target_assignees = [u1_name]
        expected_reason = "no kitsu id and no email"

    elif case == "duplicate_email":
        shared_email = f"shared_{prefix}@domain.com"
        ayon_users = [
            {"name": u1_name, "attrib": {"email": shared_email}},
            {"name": u2_name, "attrib": {"email": shared_email}},
        ]
        kitsu_persons = [
            {"id": p1_id, "name": "Person 1", "email": shared_email},
        ]
        target_assignees = [u1_name]
        expected_reason = "ayon_email_match_count_2"

    elif case == "missing_kitsu_id":
        bad_id = f"p-nonexistent-{prefix}"
        ayon_users = [
            {
                "name": u1_name,
                "attrib": {"email": u1_email},
                "data": {"kitsuId": bad_id},
            }
        ]
        kitsu_persons = [
            {"id": p1_id, "name": "Person 1", "email": u1_email},
        ]
        target_assignees = [u1_name]
        expected_reason = "kitsu id not found"

    elif case == "mismatched_kitsu_id":
        ayon_users = [
            {
                "name": u1_name,
                "attrib": {"email": u2_email},
                "data": {"kitsuId": p1_id},
            }
        ]
        kitsu_persons = [
            {"id": p1_id, "name": "Person 1", "email": u1_email},
            {"id": p2_id, "name": "Person 2", "email": u2_email},
        ]
        target_assignees = [u1_name]
        expected_reason = "mismatched_kitsu_id"

    else:  # ambiguous_email
        ambig_email = f"ambig_{prefix}@domain.com"
        ayon_users = [
            {"name": u1_name, "attrib": {"email": ambig_email}},
        ]
        kitsu_persons = [
            {"id": p1_id, "name": "Person 1", "email": ambig_email},
            {"id": p2_id, "name": "Person 2", "email": ambig_email},
        ]
        target_assignees = [u1_name]
        expected_reason = "email matches several persons"

    outside_count = count_users_outside_roundtrip_conditions(
        ayon_users, kitsu_persons
    )

    return {
        "case": case,
        "ayon_users": ayon_users,
        "kitsu_persons": kitsu_persons,
        "target_assignees": target_assignees,
        "expected_reason": expected_reason,
        "outside_count": outside_count,
    }


@settings(max_examples=100, deadline=None)
@given(setup=out_of_domain_assignee_setup())
def test_out_of_domain_assignees_echo_property_hypothesis(
    setup: Dict[str, Any],
) -> None:
    """Property 30: Out-of-domain assignees terminate without unbounded writes.

    Validates: Requirements 5.12, 7.5
    """
    case = setup["case"]
    ayon_users = setup["ayon_users"]
    kitsu_persons = setup["kitsu_persons"]
    target_assignees = setup["target_assignees"]
    outside_count = setup["outside_count"]

    assert outside_count >= 1

    ayon_task = {
        "id": "task-ood-assignees",
        "project": "test_project",
        "status": "Todo",
        "assignees": [],
        "data": {"kitsuId": "kitsu-task-ood-assignees"},
    }
    kitsu_task = {
        "id": "kitsu-task-ood-assignees",
        "project_id": "kitsu-project-1",
        "assignees": [],
        "name": "lighting",
    }

    toggles = make_default_toggles(
        task_status=False,
        task_assignees=True,
    )

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        ayon_users=ayon_users,
        kitsu_persons=kitsu_persons,
        toggles_now=toggles,
        sim_time=1000.0,
    )

    changed = sim.apply_user_ayon_assignee_change(
        target_assignees, user="coordinator"
    )
    assert changed

    steps = sim.run_until_quiescent(max_steps=50)
    assert steps > 0
    assert len(sim.event_queue) == 0

    assert sim.kitsu_writes["task_assignees"] <= 1
    assert sim.ayon_writes["task_assignees"] <= 1
    assert sim.loop_guard_fired is False

    # Assert that EVERY AYON write (inbound update or conflict pull)
    # produced a corresponding marked event, and that processing that
    # specific event added zero Kitsu writes.
    for item in sim.ayon_write_events:
        evt = item["event"]
        assert evt.get("sender_type") == "kitsu_sync"
        assert (evt.get("summary") or {}).get("kitsuSyncOrigin") is True

        trace = next(
            (t for t in sim.event_trace if t.get("event") is evt),
            None,
        )
        assert trace is not None, "Emitted sync event was not processed"
        assert trace.get("direction") == "outbound"
        assert trace.get("decision") == "skipped"
        assert trace.get("reason") == "origin sync_originated"
        assert trace["kitsu_writes_before"] == trace["kitsu_writes_after"]

    # Diagnostic assertion for ALL cases including duplicate_email
    assert len(sim.unmet_conditions) >= 1
    diag = next(
        d for d in sim.unmet_conditions
        if d.get("category") == "task_assignees"
    )
    assert diag["field"] == "assignees"
    assert diag["username"] in target_assignees
    assert diag["condition"] == setup["expected_reason"]
    assert case in (
        "empty_email",
        "duplicate_email",
        "missing_kitsu_id",
        "mismatched_kitsu_id",
        "ambiguous_email",
    )

    sim.advance_time(60.0)
    extra = sim.run_until_quiescent(max_steps=10)
    assert extra == 0


@st.composite
def out_of_domain_attrib_setup(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate out-of-domain entity attribute scenarios."""
    case = draw(st.sampled_from(["invalid_frame_range", "empty_description"]))
    if case == "invalid_frame_range":
        fstart = draw(st.integers(min_value=1100, max_value=2000))
        fend = fstart - draw(st.integers(min_value=1, max_value=100))
        changed_attribs = {"frameStart": fstart, "frameEnd": fend}
    else:  # empty_description
        changed_attribs = {"description": ""}

    return {
        "case": case,
        "changed_attribs": changed_attribs,
    }


@settings(max_examples=100, deadline=None)
@given(setup=out_of_domain_attrib_setup())
def test_out_of_domain_attributes_echo_property_hypothesis(
    setup: Dict[str, Any],
) -> None:
    """Property 30: Out-of-domain attributes terminate without Kitsu writes.

    Validates: Requirements 5.12, 8.10
    """
    case = setup["case"]
    changed_attribs = setup["changed_attribs"]

    ayon_entity = {
        "id": "folder-ood-attrib",
        "project": "test_project",
        "attrib": {
            "frameStart": 1001,
            "frameEnd": 1100,
            "fps": 24.0,
            "resolutionWidth": 1920,
            "resolutionHeight": 1080,
            "description": "Initial text",
        },
        "own_attrib": [
            "frameStart",
            "frameEnd",
            "fps",
            "resolutionWidth",
            "resolutionHeight",
            "description",
        ],
        "data": {"kitsuId": "kitsu-folder-ood"},
    }
    kitsu_entity = {
        "id": "kitsu-folder-ood",
        "project_id": "kitsu-project-1",
        "data": {
            "frame_in": 1001,
            "frame_out": 1100,
            "fps": 24.0,
            "resolution": "1920x1080",
        },
        "nb_frames": 100,
        "description": "Initial text",
    }

    toggles = make_default_toggles(
        task_status=False,
        entity_attributes=True,
    )

    sim = EchoSimulator(
        ayon_entity=ayon_entity,
        kitsu_entity=kitsu_entity,
        entity_type="folder",
        toggles_now=toggles,
        sim_time=1000.0,
    )

    changed = sim.apply_user_ayon_attrib_change(
        changed_attribs, user="pipeline_td"
    )
    assert changed

    steps = sim.run_until_quiescent(max_steps=50)
    assert steps > 0
    assert len(sim.event_queue) == 0

    if case == "invalid_frame_range":
        # Invalid frame range produces 0 Kitsu writes and reports error
        assert sim.kitsu_writes["entity_attributes"] == 0
        assert sim.ayon_writes["entity_attributes"] == 0
        assert sim.loop_guard_fired is False
        assert len(sim.unmet_conditions) >= 1
        diag = next(
            d for d in sim.unmet_conditions
            if d.get("category") == "entity_attributes"
        )
        assert diag["condition"] == "invalid_frame_range"
    else:
        # Empty description is written to Kitsu (Req 8.1), but Inbound
        # does NOT echo it back to AYON (Req 8.10 asymmetry)
        assert sim.kitsu_writes["entity_attributes"] == 1
        assert sim.ayon_writes["entity_attributes"] == 0
        assert sim.loop_guard_fired is False

    for item in sim.ayon_write_events:
        evt = item["event"]
        assert evt.get("sender_type") == "kitsu_sync"
        assert (evt.get("summary") or {}).get("kitsuSyncOrigin") is True

        trace = next(
            (t for t in sim.event_trace if t.get("event") is evt),
            None,
        )
        assert trace is not None
        assert trace.get("direction") == "outbound"
        assert trace.get("decision") == "skipped"
        assert trace.get("reason") == "origin sync_originated"
        assert trace["kitsu_writes_before"] == trace["kitsu_writes_after"]

    sim.advance_time(60.0)
    extra = sim.run_until_quiescent(max_steps=10)
    assert extra == 0


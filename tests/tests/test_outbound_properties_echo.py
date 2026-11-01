"""Property test for bounded echo (task status, assignees, attributes).

Validates: Requirements 5.3, 5.5, 7.5, 8.4, 8.7
"""

# Feature: kitsu-two-way-sync, Property 9: Bounded echo

from typing import Any, Dict, List

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from .offline import block_network  # noqa: F401
from .outbound_sim import EchoSimulator, make_default_toggles

pytestmark = pytest.mark.usefixtures("block_network")


@st.composite
def lossless_status_setup(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate valid non-archived Kitsu statuses in Lossless_Mapping_Domain.

    Ensures at least three distinct non-archived statuses (A, B, C) and
    optional archived statuses.
    """
    raw_names = draw(
        st.sets(
            st.text(
                alphabet=st.characters(
                    blacklist_categories=("Cs", "Cc", "Zs"),
                    min_codepoint=33,
                    max_codepoint=126,
                ),
                min_size=1,
                max_size=30,
            ),
            min_size=3,
            max_size=6,
        )
    )
    names_list = sorted(raw_names)
    status_a = names_list[0]
    status_b = names_list[1]
    status_c = names_list[2]

    statuses: List[Dict[str, Any]] = [
        {"id": f"stat-id-{idx}", "name": name, "archived": False}
        for idx, name in enumerate(names_list)
    ]

    # Optionally add archived statuses with random names
    add_archived = draw(st.booleans())
    if add_archived:
        statuses.append({
            "id": "archived-1",
            "name": f"Archived_{status_a}",
            "archived": True,
        })

    policy = draw(st.sampled_from(["kitsu_wins", "ayon_wins"]))
    scenario = draw(st.sampled_from(["normal", "in_sync", "conflict"]))

    return {
        "statuses": statuses,
        "status_a": status_a,
        "status_b": status_b,
        "status_c": status_c,
        "policy": policy,
        "scenario": scenario,
    }


@settings(max_examples=100, deadline=None)
@given(setup=lossless_status_setup())
def test_bounded_echo_property_hypothesis(setup: Dict[str, Any]) -> None:
    """Property 9: Bounded echo for task status changes."""
    statuses = setup["statuses"]
    status_a = setup["status_a"]
    status_b = setup["status_b"]
    status_c = setup["status_c"]
    policy = setup["policy"]
    scenario = setup["scenario"]

    id_map = {s["name"]: s["id"] for s in statuses if not s["archived"]}

    # Initial state: AYON is at status_a
    ayon_task = {
        "id": "task-entity-1",
        "project": "test_project",
        "status": status_a,
        "data": {"kitsuId": "kitsu-task-1"},
    }

    # Set initial Kitsu state based on scenario
    if scenario == "normal":
        kitsu_curr_name = status_a
    elif scenario == "in_sync":
        kitsu_curr_name = status_b
    else:  # conflict
        kitsu_curr_name = status_c

    kitsu_task = {
        "id": "kitsu-task-1",
        "project_id": "kitsu-project-1",
        "task_status_id": id_map[kitsu_curr_name],
        "name": "animation",
    }

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        kitsu_statuses=statuses,
        conflict_policy=policy,
        sim_time=1000.0,
    )

    # User changes AYON task from status_a to status_b
    changed = sim.apply_user_ayon_status_change(status_b, user="coordinator")
    if scenario == "in_sync" and status_a == status_b:
        assert not changed
        return
    assert changed

    # Run simulation until quiescent
    steps = sim.run_until_quiescent(max_steps=50)
    assert steps > 0
    assert len(sim.event_queue) == 0

    # Evaluate bounds based on scenario
    if scenario == "normal":
        # AYON A->B, Kitsu was A -> exactly 1 Kitsu write, 0 AYON writes
        assert sim.kitsu_writes["task_status"] == 1
        assert sim.ayon_writes["task_status"] == 0
        assert sim.kitsu_state["task_status_id"] == id_map[status_b]
        assert sim.ayon_state["status"] == status_b

    elif scenario == "in_sync":
        # AYON A->B, but Kitsu already at B -> 0 Kitsu writes, 0 AYON writes
        assert sim.kitsu_writes["task_status"] == 0
        assert sim.ayon_writes["task_status"] == 0
        assert sim.kitsu_state["task_status_id"] == id_map[status_b]
        assert sim.ayon_state["status"] == status_b

    elif scenario == "conflict":
        if policy == "ayon_wins":
            # Outbound overwrites Kitsu with status_b
            assert sim.kitsu_writes["task_status"] == 1
            assert sim.ayon_writes["task_status"] == 0
            assert sim.kitsu_state["task_status_id"] == id_map[status_b]
            assert sim.ayon_state["status"] == status_b
        else:
            # kitsu_wins: Inbound pulls status_c to AYON
            assert sim.kitsu_writes["task_status"] == 0
            assert sim.ayon_writes["task_status"] == 1
            assert sim.kitsu_state["task_status_id"] == id_map[status_c]
            assert sim.ayon_state["status"] == status_c

    # Assert all inbound-originated AYON events have both sync markers
    for trace in sim.event_trace:
        if trace.get("decision") == "conflict_keep_kitsu":
            continue
        if trace.get("direction") == "inbound" and trace.get("written_value"):
            # Check the queued event generated by this write
            marked_evts = [
                t["event"]
                for t in sim.event_trace
                if t.get("direction") == "outbound"
                and t.get("reason", "").startswith("origin")
            ]
            for m in marked_evts:
                assert m.get("sender_type") == "kitsu_sync"
                assert (m.get("summary") or {}).get("kitsuSyncOrigin") is True

    # Advance 60 simulated seconds: assert no further writes
    snapshot_kitsu_writes = sim.kitsu_writes["task_status"]
    snapshot_ayon_writes = sim.ayon_writes["task_status"]

    sim.advance_time(60.0)
    extra_steps = sim.run_until_quiescent(max_steps=10)
    assert extra_steps == 0
    assert sim.kitsu_writes["task_status"] == snapshot_kitsu_writes
    assert sim.ayon_writes["task_status"] == snapshot_ayon_writes


@pytest.mark.parametrize(
    "kitsu_curr,prev,new,policy,expected_kwrites,expected_awrites,final_name",
    [
        ("A", "A", "B", "kitsu_wins", 1, 0, "B"),
        ("A", "A", "B", "ayon_wins", 1, 0, "B"),
        ("B", "A", "B", "kitsu_wins", 0, 0, "B"),
        ("B", "A", "B", "ayon_wins", 0, 0, "B"),
        ("C", "A", "B", "ayon_wins", 1, 0, "B"),
        ("C", "A", "B", "kitsu_wins", 0, 1, "C"),
    ],
)
def test_bounded_echo_deterministic_matrix(
    kitsu_curr: str,
    prev: str,
    new: str,
    policy: str,
    expected_kwrites: int,
    expected_awrites: int,
    final_name: str,
) -> None:
    """Validate all rows of the echo decision and conflict matrix."""
    statuses = [
        {"id": "id-A", "name": "A", "archived": False},
        {"id": "id-B", "name": "B", "archived": False},
        {"id": "id-C", "name": "C", "archived": False},
    ]

    ayon_task = {
        "id": "task-entity-matrix",
        "project": "test_project",
        "status": prev,
        "data": {"kitsuId": "kitsu-task-matrix"},
    }
    kitsu_task = {
        "id": "kitsu-task-matrix",
        "project_id": "kitsu-project-matrix",
        "task_status_id": f"id-{kitsu_curr}",
        "name": "lighting",
    }

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        kitsu_statuses=statuses,
        conflict_policy=policy,
        sim_time=1000.0,
    )

    sim.apply_user_ayon_status_change(new, user="bob")
    sim.run_until_quiescent(max_steps=50)

    assert sim.kitsu_writes["task_status"] == expected_kwrites
    assert sim.ayon_writes["task_status"] == expected_awrites
    assert sim.ayon_state["status"] == final_name
    assert sim.kitsu_state["task_status_id"] == f"id-{final_name}"
    assert len(sim.event_queue) == 0

    # Extra 60 seconds adds zero writes
    sim.advance_time(60.0)
    sim.run_until_quiescent(max_steps=10)
    assert sim.kitsu_writes["task_status"] == expected_kwrites
    assert sim.ayon_writes["task_status"] == expected_awrites


@st.composite
def lossless_assignee_setup(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate valid users meeting Requirement 7.5 conditions."""
    user_names = ["alice", "bob", "carol"]
    kitsu_persons = [
        {
            "id": f"p-{name}",
            "name": name.title(),
            "email": f"{name}@studio.com",
        }
        for name in user_names
    ]
    has_unmanaged = draw(st.booleans())
    if has_unmanaged:
        kitsu_persons.append({
            "id": "p-ext",
            "name": "External",
            "email": "ext@vendor.com",
        })

    ayon_users = [
        {
            "name": name,
            "attrib": {"email": f"{name}@studio.com"},
            "data": {"kitsuId": f"p-{name}"},
        }
        for name in user_names
    ]

    assignee_choices = [
        ["alice"],
        ["bob"],
        ["carol"],
        ["alice", "bob"],
        ["bob", "carol"],
        [],
    ]
    perm = draw(st.permutations(assignee_choices))
    assignees_a = list(perm[0])
    assignees_b = list(perm[1])
    assignees_c = list(perm[2])

    policy = draw(st.sampled_from(["kitsu_wins", "ayon_wins"]))
    scenario = draw(st.sampled_from(["normal", "in_sync", "conflict"]))

    return {
        "ayon_users": ayon_users,
        "kitsu_persons": kitsu_persons,
        "assignees_a": assignees_a,
        "assignees_b": assignees_b,
        "assignees_c": assignees_c,
        "policy": policy,
        "scenario": scenario,
        "has_unmanaged": has_unmanaged,
    }


@settings(max_examples=100, deadline=None)
@given(setup=lossless_assignee_setup())
def test_bounded_echo_assignees_hypothesis(setup: Dict[str, Any]) -> None:
    """Property 9: Bounded echo for task assignees changes (Slice 2)."""
    ayon_users = setup["ayon_users"]
    kitsu_persons = setup["kitsu_persons"]
    assignees_a = setup["assignees_a"]
    assignees_b = setup["assignees_b"]
    assignees_c = setup["assignees_c"]
    policy = setup["policy"]
    scenario = setup["scenario"]
    has_unmanaged = setup["has_unmanaged"]

    name_to_pid = {p["name"].lower(): p["id"] for p in kitsu_persons}
    unmanaged_ids = ["p-ext"] if has_unmanaged else []

    ayon_task = {
        "id": "task-entity-assignees",
        "project": "test_project",
        "status": "Todo",
        "assignees": list(assignees_a),
        "data": {"kitsuId": "kitsu-task-assignees"},
    }

    if scenario == "normal":
        kitsu_curr_names = assignees_a
    elif scenario == "in_sync":
        kitsu_curr_names = assignees_b
    else:  # conflict
        kitsu_curr_names = assignees_c

    kitsu_curr_pids = sorted(
        [name_to_pid[n] for n in kitsu_curr_names if n in name_to_pid]
        + unmanaged_ids
    )
    kitsu_task = {
        "id": "kitsu-task-assignees",
        "project_id": "kitsu-project-1",
        "assignees": kitsu_curr_pids,
        "name": "lighting",
    }

    toggles = make_default_toggles(
        task_status=False,
        task_assignees=True,
        conflict_policy=policy,
    )

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        ayon_users=ayon_users,
        kitsu_persons=kitsu_persons,
        toggles_now=toggles,
        conflict_policy=policy,
        sim_time=1000.0,
    )

    changed = sim.apply_user_ayon_assignee_change(
        assignees_b, user="coordinator"
    )
    if scenario == "in_sync" and sorted(assignees_a) == sorted(assignees_b):
        assert not changed
        return
    assert changed

    steps = sim.run_until_quiescent(max_steps=50)
    assert steps > 0
    assert len(sim.event_queue) == 0

    if scenario == "normal":
        assert sim.kitsu_writes["task_assignees"] == 1
        assert sim.ayon_writes["task_assignees"] == 0
        expected_pids = sorted(
            [name_to_pid[n] for n in assignees_b if n in name_to_pid]
            + unmanaged_ids
        )
        assert sim.kitsu_state["assignees"] == expected_pids
        assert sim.ayon_state["assignees"] == assignees_b

    elif scenario == "in_sync":
        assert sim.kitsu_writes["task_assignees"] == 0
        assert sim.ayon_writes["task_assignees"] == 0
        assert sim.ayon_state["assignees"] == assignees_b

    elif scenario == "conflict":
        if policy == "ayon_wins":
            assert sim.kitsu_writes["task_assignees"] == 1
            assert sim.ayon_writes["task_assignees"] == 0
            expected_pids = sorted(
                [name_to_pid[n] for n in assignees_b if n in name_to_pid]
                + unmanaged_ids
            )
            assert sim.kitsu_state["assignees"] == expected_pids
            assert sim.ayon_state["assignees"] == assignees_b
        else:
            assert sim.kitsu_writes["task_assignees"] == 0
            assert sim.ayon_writes["task_assignees"] == 1
            expected_ayon = sorted(
                [n for n in kitsu_curr_names if n in name_to_pid]
            )
            assert sorted(sim.ayon_state["assignees"]) == expected_ayon

    # Extra 60 seconds adds zero writes (Req 5.5)
    kw_snap = sim.kitsu_writes["task_assignees"]
    aw_snap = sim.ayon_writes["task_assignees"]
    sim.advance_time(60.0)
    extra = sim.run_until_quiescent(max_steps=10)
    assert extra == 0
    assert sim.kitsu_writes["task_assignees"] == kw_snap
    assert sim.ayon_writes["task_assignees"] == aw_snap


@st.composite
def lossless_attrib_setup(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate valid entity attributes inside Requirement 8.7 ranges."""
    fstart = draw(st.integers(min_value=1000, max_value=2000))
    fend = draw(st.integers(min_value=fstart, max_value=fstart + 500))
    fps = draw(st.sampled_from([24.0, 25.0, 30.0, 23.976]))
    rw = draw(st.sampled_from([1920, 2048, 3840]))
    rh = draw(st.sampled_from([1080, 1152, 2160]))
    desc = draw(
        st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs", "Cc"),
                min_codepoint=32,
                max_codepoint=126,
            ),
            min_size=1,
            max_size=30,
        )
    )

    attribs_a = {
        "frameStart": fstart,
        "frameEnd": fend,
        "fps": fps,
        "resolutionWidth": rw,
        "resolutionHeight": rh,
        "description": desc,
    }
    attribs_b = dict(attribs_a)
    attribs_c = dict(attribs_a)

    field_choice = draw(
        st.sampled_from(["fps", "description", "frame_range", "resolution"])
    )
    if field_choice == "fps":
        fps_choices = [f for f in [24.0, 25.0, 30.0, 23.976] if f != fps]
        attribs_b["fps"] = fps_choices[0]
        attribs_c["fps"] = fps_choices[1]
    elif field_choice == "description":
        attribs_b["description"] = f"{desc}_B"
        attribs_c["description"] = f"{desc}_C"
    elif field_choice == "frame_range":
        attribs_b["frameEnd"] = fend + 50
        attribs_c["frameEnd"] = fend + 100
    else:
        res_choices = [(1920, 1080), (2048, 1152), (3840, 2160)]
        perm = draw(st.permutations(res_choices))
        attribs_a["resolutionWidth"], attribs_a["resolutionHeight"] = (
            perm[0]
        )
        attribs_b["resolutionWidth"], attribs_b["resolutionHeight"] = (
            perm[1]
        )
        attribs_c["resolutionWidth"], attribs_c["resolutionHeight"] = (
            perm[2]
        )

    policy = draw(st.sampled_from(["kitsu_wins", "ayon_wins"]))
    scenario = draw(st.sampled_from(["normal", "in_sync", "conflict"]))

    return {
        "attribs_a": attribs_a,
        "attribs_b": attribs_b,
        "attribs_c": attribs_c,
        "policy": policy,
        "scenario": scenario,
        "field_choice": field_choice,
    }


@settings(max_examples=100, deadline=None)
@given(setup=lossless_attrib_setup())
def test_bounded_echo_attributes_hypothesis(setup: Dict[str, Any]) -> None:
    """Property 9: Bounded echo for entity attributes changes (Slice 2)."""
    attribs_a = setup["attribs_a"]
    attribs_b = setup["attribs_b"]
    attribs_c = setup["attribs_c"]
    policy = setup["policy"]
    scenario = setup["scenario"]

    ayon_entity = {
        "id": "folder-entity-attrib",
        "project": "test_project",
        "attrib": dict(attribs_a),
        "own_attrib": list(attribs_a.keys()),
        "data": {"kitsuId": "kitsu-folder-attrib"},
    }

    if scenario == "normal":
        k_curr = attribs_a
    elif scenario == "in_sync":
        k_curr = attribs_b
    else:  # conflict
        k_curr = attribs_c

    res_str = f"{k_curr['resolutionWidth']}x{k_curr['resolutionHeight']}"
    kitsu_data = {
        "frame_in": k_curr["frameStart"],
        "frame_out": k_curr["frameEnd"],
        "fps": k_curr["fps"],
        "resolution": res_str,
        "custom_editorial_key": "editorial_preserve_check",
    }
    kitsu_entity = {
        "id": "kitsu-folder-attrib",
        "project_id": "kitsu-project-1",
        "data": kitsu_data,
        "nb_frames": k_curr["frameEnd"] - k_curr["frameStart"] + 1,
        "description": k_curr["description"],
    }

    toggles = make_default_toggles(
        task_status=False,
        entity_attributes=True,
        conflict_policy=policy,
    )

    sim = EchoSimulator(
        ayon_entity=ayon_entity,
        kitsu_entity=kitsu_entity,
        entity_type="folder",
        toggles_now=toggles,
        conflict_policy=policy,
        sim_time=1000.0,
    )

    changed = sim.apply_user_ayon_attrib_change(
        attribs_b, user="pipeline_td"
    )
    if scenario == "in_sync" and attribs_a == attribs_b:
        assert not changed
        return
    assert changed

    steps = sim.run_until_quiescent(max_steps=50)
    assert steps > 0
    assert len(sim.event_queue) == 0

    if scenario == "normal":
        assert sim.kitsu_writes["entity_attributes"] == 1
        assert sim.ayon_writes["entity_attributes"] == 0
        assert sim.kitsu_state["data"]["frame_in"] == attribs_b["frameStart"]
        assert sim.kitsu_state["data"]["frame_out"] == attribs_b["frameEnd"]
        assert sim.kitsu_state["description"] == attribs_b["description"]

    elif scenario == "in_sync":
        assert sim.kitsu_writes["entity_attributes"] == 0
        assert sim.ayon_writes["entity_attributes"] == 0

    elif scenario == "conflict":
        if policy == "ayon_wins":
            assert sim.kitsu_writes["entity_attributes"] == 1
            assert sim.ayon_writes["entity_attributes"] == 0
        else:
            assert sim.kitsu_writes["entity_attributes"] == 0
            assert sim.ayon_writes["entity_attributes"] == 1

    # Requirement 8.4: Unrelated data keys strictly preserved
    assert (
        sim.kitsu_state["data"].get("custom_editorial_key")
        == "editorial_preserve_check"
    )

    # Extra 60 seconds adds zero writes (Req 5.5)
    kw_snap = sim.kitsu_writes["entity_attributes"]
    aw_snap = sim.ayon_writes["entity_attributes"]
    sim.advance_time(60.0)
    extra = sim.run_until_quiescent(max_steps=10)
    assert extra == 0
    assert sim.kitsu_writes["entity_attributes"] == kw_snap
    assert sim.ayon_writes["entity_attributes"] == aw_snap


@pytest.mark.parametrize(
    "k_curr,prev,new,policy,expected_kw,expected_aw,final_assignees",
    [
        (["alice"], ["alice"], ["bob"], "kitsu_wins", 1, 0, ["bob"]),
        (["alice"], ["alice"], ["bob"], "ayon_wins", 1, 0, ["bob"]),
        (["bob"], ["alice"], ["bob"], "kitsu_wins", 0, 0, ["bob"]),
        (["bob"], ["alice"], ["bob"], "ayon_wins", 0, 0, ["bob"]),
        (["carol"], ["alice"], ["bob"], "ayon_wins", 1, 0, ["bob"]),
        (["carol"], ["alice"], ["bob"], "kitsu_wins", 0, 1, ["carol"]),
    ],
)
def test_bounded_echo_assignees_deterministic_matrix(
    k_curr: List[str],
    prev: List[str],
    new: List[str],
    policy: str,
    expected_kw: int,
    expected_aw: int,
    final_assignees: List[str],
) -> None:
    """Validate all rows of the assignee echo and conflict matrix."""
    user_names = ["alice", "bob", "carol"]
    ayon_users = [
        {
            "name": name,
            "attrib": {"email": f"{name}@studio.com"},
            "data": {"kitsuId": f"p-{name}"},
        }
        for name in user_names
    ]
    kitsu_persons = [
        {
            "id": f"p-{name}",
            "name": name.title(),
            "email": f"{name}@studio.com",
        }
        for name in user_names
    ]
    name_to_pid = {name: f"p-{name}" for name in user_names}

    ayon_task = {
        "id": "task-det-assignees",
        "project": "test_project",
        "status": "Todo",
        "assignees": list(prev),
        "data": {"kitsuId": "kitsu-task-det-assignees"},
    }
    kitsu_task = {
        "id": "kitsu-task-det-assignees",
        "project_id": "kitsu-project-1",
        "assignees": [name_to_pid[n] for n in k_curr],
        "name": "lighting",
    }

    toggles = make_default_toggles(
        task_status=False,
        task_assignees=True,
        conflict_policy=policy,
    )

    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        ayon_users=ayon_users,
        kitsu_persons=kitsu_persons,
        toggles_now=toggles,
        conflict_policy=policy,
        sim_time=1000.0,
    )

    sim.apply_user_ayon_assignee_change(new, user="coordinator")
    sim.run_until_quiescent(max_steps=50)

    assert sim.kitsu_writes["task_assignees"] == expected_kw
    assert sim.ayon_writes["task_assignees"] == expected_aw
    assert sorted(sim.ayon_state["assignees"]) == sorted(final_assignees)
    expected_final_pids = sorted([name_to_pid[n] for n in final_assignees])
    assert sim.kitsu_state["assignees"] == expected_final_pids

    sim.advance_time(60.0)
    sim.run_until_quiescent(max_steps=10)
    assert sim.kitsu_writes["task_assignees"] == expected_kw
    assert sim.ayon_writes["task_assignees"] == expected_aw


@pytest.mark.parametrize(
    "k_fps,prev_fps,new_fps,policy,expected_kw,expected_aw,final_fps",
    [
        (24.0, 24.0, 30.0, "kitsu_wins", 1, 0, 30.0),
        (24.0, 24.0, 30.0, "ayon_wins", 1, 0, 30.0),
        (30.0, 24.0, 30.0, "kitsu_wins", 0, 0, 30.0),
        (30.0, 24.0, 30.0, "ayon_wins", 0, 0, 30.0),
        (60.0, 24.0, 30.0, "ayon_wins", 1, 0, 30.0),
        (60.0, 24.0, 30.0, "kitsu_wins", 0, 1, 60.0),
    ],
)
def test_bounded_echo_attributes_deterministic_matrix(
    k_fps: float,
    prev_fps: float,
    new_fps: float,
    policy: str,
    expected_kw: int,
    expected_aw: int,
    final_fps: float,
) -> None:
    """Validate all rows of the attribute echo and conflict matrix."""
    ayon_entity = {
        "id": "folder-det-attrib",
        "project": "test_project",
        "attrib": {
            "frameStart": 1001,
            "frameEnd": 1100,
            "fps": prev_fps,
            "resolutionWidth": 1920,
            "resolutionHeight": 1080,
            "description": "Det test",
        },
        "own_attrib": ["fps"],
        "data": {"kitsuId": "kitsu-folder-det-attrib"},
    }
    kitsu_entity = {
        "id": "kitsu-folder-det-attrib",
        "project_id": "kitsu-project-1",
        "data": {
            "frame_in": 1001,
            "frame_out": 1100,
            "fps": k_fps,
            "resolution": "1920x1080",
            "editorial_meta": "keep_this_key",
        },
        "nb_frames": 100,
        "description": "Det test",
    }

    toggles = make_default_toggles(
        task_status=False,
        entity_attributes=True,
        conflict_policy=policy,
    )

    sim = EchoSimulator(
        ayon_entity=ayon_entity,
        kitsu_entity=kitsu_entity,
        entity_type="folder",
        toggles_now=toggles,
        conflict_policy=policy,
        sim_time=1000.0,
    )

    sim.apply_user_ayon_attrib_change({"fps": new_fps}, user="pipeline_td")
    sim.run_until_quiescent(max_steps=50)

    assert sim.kitsu_writes["entity_attributes"] == expected_kw
    assert sim.ayon_writes["entity_attributes"] == expected_aw
    assert sim.ayon_state["attrib"]["fps"] == final_fps
    assert sim.kitsu_state["data"]["fps"] == final_fps
    assert sim.kitsu_state["data"]["editorial_meta"] == "keep_this_key"

    sim.advance_time(60.0)
    sim.run_until_quiescent(max_steps=10)
    assert sim.kitsu_writes["entity_attributes"] == expected_kw
    assert sim.ayon_writes["entity_attributes"] == expected_aw


def test_inbound_assignees_reversed_order_saves_once_and_terminates() -> None:
    """Requirement 7.5 & server update_task list equality:
    Reversed order updates AYON once with marked sync event and quiesces.
    """
    user_names = ["alice", "bob"]
    ayon_users = [
        {
            "name": name,
            "attrib": {"email": f"{name}@studio.com"},
            "data": {"kitsuId": f"p-{name}"},
        }
        for name in user_names
    ]
    kitsu_persons = [
        {
            "id": f"p-{name}",
            "name": name.title(),
            "email": f"{name}@studio.com",
        }
        for name in user_names
    ]

    # AYON has ["alice", "bob"]
    ayon_task = {
        "id": "task-order-1",
        "project": "test_project",
        "status": "Todo",
        "assignees": ["alice", "bob"],
        "data": {"kitsuId": "kitsu-task-order-1"},
    }
    # Kitsu has reversed order: ["p-bob", "p-alice"]
    kitsu_task = {
        "id": "kitsu-task-order-1",
        "project_id": "kitsu-project-1",
        "assignees": ["p-bob", "p-alice"],
        "name": "comp",
    }

    toggles = make_default_toggles(task_status=False, task_assignees=True)
    sim = EchoSimulator(
        ayon_task=ayon_task,
        kitsu_task=kitsu_task,
        ayon_users=ayon_users,
        kitsu_persons=kitsu_persons,
        toggles_now=toggles,
        sim_time=1000.0,
    )

    # Inbound event from Kitsu with reversed list
    sim.event_queue.append({
        "type": "kitsu",
        "event": "task:update",
        "task_id": "kitsu-task-order-1",
        "category": "task_assignees",
        "createdAt": 1000.0,
    })

    steps = sim.run_until_quiescent(max_steps=20)
    assert steps > 0
    # Inbound saved AYON task once with Kitsu's order
    assert sim.ayon_writes["task_assignees"] == 1
    assert sim.ayon_state["assignees"] == ["bob", "alice"]
    # Outbound skipped the marked sync event: zero Kitsu writes
    assert sim.kitsu_writes["task_assignees"] == 0
    assert len(sim.event_queue) == 0

    # Matching order case produces 0 writes
    sim_matching = EchoSimulator(
        ayon_task={
            "id": "task-order-2",
            "project": "test_project",
            "status": "Todo",
            "assignees": ["bob", "alice"],
            "data": {"kitsuId": "kitsu-task-order-2"},
        },
        kitsu_task={
            "id": "kitsu-task-order-2",
            "project_id": "kitsu-project-1",
            "assignees": ["p-bob", "p-alice"],
            "name": "comp",
        },
        ayon_users=ayon_users,
        kitsu_persons=kitsu_persons,
        toggles_now=toggles,
        sim_time=1000.0,
    )
    sim_matching.event_queue.append({
        "type": "kitsu",
        "event": "task:update",
        "task_id": "kitsu-task-order-2",
        "category": "task_assignees",
        "createdAt": 1000.0,
    })
    sim_matching.run_until_quiescent(max_steps=20)
    assert sim_matching.ayon_writes["task_assignees"] == 0
    assert sim_matching.kitsu_writes["task_assignees"] == 0


def test_mixed_attribute_conflict_writes_non_conflicting_and_pulls() -> None:
    """Requirement 9.2: kitsu_wins writes non-conflicting and pulls conflict.
    """
    ayon_entity = {
        "id": "folder-mixed-conflict",
        "project": "test_project",
        "attrib": {
            "fps": 24.0,
            "description": "Old AYON Desc",
            "frameStart": 1001,
            "frameEnd": 1100,
        },
        "own_attrib": ["fps", "description"],
        "data": {"kitsuId": "kitsu-folder-mixed"},
    }
    # Kitsu: fps is 24.0 (in sync with prev), description changed
    kitsu_entity = {
        "id": "kitsu-folder-mixed",
        "project_id": "kitsu-project-1",
        "data": {
            "fps": 24.0,
            "frame_in": 1001,
            "frame_out": 1100,
        },
        "nb_frames": 100,
        "description": "Kitsu Desc",
    }

    toggles = make_default_toggles(
        task_status=False,
        entity_attributes=True,
        conflict_policy="kitsu_wins",
    )

    sim = EchoSimulator(
        ayon_entity=ayon_entity,
        kitsu_entity=kitsu_entity,
        entity_type="folder",
        toggles_now=toggles,
        conflict_policy="kitsu_wins",
        sim_time=1000.0,
    )

    # User changes both fps and description in AYON
    sim.apply_user_ayon_attrib_change(
        {"fps": 30.0, "description": "New AYON Desc"},
        user="pipeline_td",
    )
    sim.run_until_quiescent(max_steps=50)

    # Outbound wrote non-conflicting fps to Kitsu
    assert sim.kitsu_writes["entity_attributes"] == 1
    assert sim.kitsu_state["data"]["fps"] == 30.0
    # Conflicting description was kept from Kitsu and pulled inbound to AYON
    assert sim.kitsu_state["description"] == "Kitsu Desc"
    assert sim.ayon_state["attrib"]["description"] == "Kitsu Desc"
    assert sim.ayon_state["attrib"]["fps"] == 30.0
    # Inbound pull performed 1 marked write to AYON, which outbound skipped
    assert sim.ayon_writes["entity_attributes"] == 1
    assert len(sim.event_queue) == 0

    # Advance 60s: no extra writes
    sim.advance_time(60.0)
    sim.run_until_quiescent(max_steps=10)
    assert sim.kitsu_writes["entity_attributes"] == 1
    assert sim.ayon_writes["entity_attributes"] == 1




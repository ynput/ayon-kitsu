"""Bounded-echo checks that drive the real OutboundJobRunner.

``EchoSimulator`` re-implements the outbound handlers. These tests run
the production runner and handlers against the in-memory fakes. Only
the addon server's inbound ``/push`` is simulated (see
``outbound_echo_rig``). Disabling a production conflict pull or write
makes these fail, which the simulator-based tests cannot detect.
"""

from typing import Any, Dict, List

import pytest
from hypothesis import given, settings

from .offline import block_network  # noqa: F401
from .outbound_echo_rig import (
    AssigneeEchoRig,
    AttribEchoRig,
    StatusEchoRig,
)
from .test_outbound_properties_echo import (
    lossless_assignee_setup,
    lossless_attrib_setup,
    lossless_status_setup,
)

pytestmark = pytest.mark.usefixtures("block_network")

USER_NAMES = ("alice", "bob", "carol")
AYON_USERS = [
    {
        "name": n,
        "attrib": {"email": f"{n}@studio.com"},
        "data": {"kitsuId": f"p-{n}"},
    }
    for n in USER_NAMES
]
KITSU_PERSONS = [
    {"id": f"p-{n}", "name": n.title(), "email": f"{n}@studio.com"}
    for n in USER_NAMES
]
NAME_TO_PID = {n: f"p-{n}" for n in USER_NAMES}

ABC = [
    {"id": f"id-{n}", "name": n, "archived": False} for n in ("A", "B", "C")
]


def _assert_settled(rig, kitsu_writes: int, ayon_writes: int) -> None:
    """Assert write counts and that time passing adds no writes."""
    assert rig.kitsu_writes == kitsu_writes
    assert rig.ayon_writes == ayon_writes
    rig.clock.advance(60.0)
    assert rig.run_until_quiescent(max_steps=10) == 0
    assert rig.kitsu_writes == kitsu_writes
    assert rig.ayon_writes == ayon_writes


# ---------------------------------------------------------------------
# Task status
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "kitsu_curr,prev,new,policy,expected_kwrites,expected_awrites,final",
    [
        ("A", "A", "B", "kitsu_wins", 1, 0, "B"),
        ("A", "A", "B", "ayon_wins", 1, 0, "B"),
        ("B", "A", "B", "kitsu_wins", 0, 0, "B"),
        ("B", "A", "B", "ayon_wins", 0, 0, "B"),
        ("C", "A", "B", "ayon_wins", 1, 0, "B"),
        ("C", "A", "B", "kitsu_wins", 0, 1, "C"),
    ],
)
def test_status_echo_matrix(
    kitsu_curr, prev, new, policy, expected_kwrites, expected_awrites, final
):
    """Status decision and conflict matrix on production code."""
    rig = StatusEchoRig(ABC, prev, kitsu_curr, policy)
    rig.user_changes_status(new)

    assert rig.run_until_quiescent() > 0

    assert rig.ayon_state["status"] == final
    assert rig.kitsu_state["task_status_id"] == f"id-{final}"
    _assert_settled(rig, expected_kwrites, expected_awrites)


@settings(max_examples=100, deadline=None)
@given(setup=lossless_status_setup())
def test_status_echo_property(setup: Dict[str, Any]) -> None:
    """Bounded echo for status over generated names and scenarios."""
    names = {s["name"]: s["id"] for s in setup["statuses"]}
    a, b, c = setup["status_a"], setup["status_b"], setup["status_c"]
    scenario, policy = setup["scenario"], setup["policy"]
    kitsu_curr = {"normal": a, "in_sync": b, "conflict": c}[scenario]

    rig = StatusEchoRig(setup["statuses"], a, kitsu_curr, policy)
    assert rig.user_changes_status(b)
    assert rig.run_until_quiescent() > 0

    if scenario == "conflict" and policy == "kitsu_wins":
        expected = (0, 1, c)
    elif scenario == "in_sync":
        expected = (0, 0, b)
    else:
        expected = (1, 0, b)
    kwrites, awrites, final = expected
    assert rig.ayon_state["status"] == final
    assert rig.kitsu_state["task_status_id"] == names[final]
    _assert_settled(rig, kwrites, awrites)


# ---------------------------------------------------------------------
# Task assignees
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "k_curr,prev,new,policy,expected_kw,expected_aw,final",
    [
        (["alice"], ["alice"], ["bob"], "kitsu_wins", 1, 0, ["bob"]),
        (["alice"], ["alice"], ["bob"], "ayon_wins", 1, 0, ["bob"]),
        (["bob"], ["alice"], ["bob"], "kitsu_wins", 0, 0, ["bob"]),
        (["bob"], ["alice"], ["bob"], "ayon_wins", 0, 0, ["bob"]),
        (["carol"], ["alice"], ["bob"], "ayon_wins", 1, 0, ["bob"]),
        (["carol"], ["alice"], ["bob"], "kitsu_wins", 0, 1, ["carol"]),
    ],
)
def test_assignee_echo_matrix(
    k_curr: List[str],
    prev: List[str],
    new: List[str],
    policy: str,
    expected_kw: int,
    expected_aw: int,
    final: List[str],
) -> None:
    """Assignee decision and conflict matrix on production code."""
    rig = AssigneeEchoRig(
        AYON_USERS,
        KITSU_PERSONS,
        prev,
        [NAME_TO_PID[n] for n in k_curr],
        policy,
    )
    rig.user_changes_assignees(new)

    rig.run_until_quiescent()

    assert sorted(rig.ayon_state["assignees"]) == sorted(final)
    assert rig.kitsu_state["assignees"] == sorted(
        NAME_TO_PID[n] for n in final
    )
    _assert_settled(rig, expected_kw, expected_aw)


@settings(max_examples=100, deadline=None)
@given(setup=lossless_assignee_setup())
def test_assignee_echo_property(setup: Dict[str, Any]) -> None:
    """Bounded echo for assignees, preserving unmanaged persons."""
    persons = setup["kitsu_persons"]
    a, b, c = (setup[f"assignees_{k}"] for k in "abc")
    scenario, policy = setup["scenario"], setup["policy"]
    name_to_pid = {p["name"].lower(): p["id"] for p in persons}
    unmanaged = ["p-ext"] if setup["has_unmanaged"] else []

    def pids(names: List[str]) -> List[str]:
        return sorted(
            [name_to_pid[n] for n in names if n in name_to_pid] + unmanaged
        )

    kitsu_names = {"normal": a, "in_sync": b, "conflict": c}[scenario]
    rig = AssigneeEchoRig(
        setup["ayon_users"], persons, a, pids(kitsu_names), policy
    )
    changed = rig.user_changes_assignees(b)
    if scenario == "in_sync" and sorted(a) == sorted(b):
        assert not changed
        return
    assert changed
    assert rig.run_until_quiescent() > 0

    if scenario == "conflict" and policy == "kitsu_wins":
        assert sorted(rig.ayon_state["assignees"]) == sorted(
            n for n in kitsu_names if n in name_to_pid
        )
        counts = (0, 1)
    elif scenario == "in_sync":
        assert rig.ayon_state["assignees"] == b
        counts = (0, 0)
    else:
        assert rig.kitsu_state["assignees"] == pids(b)
        assert rig.ayon_state["assignees"] == b
        counts = (1, 0)
    _assert_settled(rig, *counts)


# ---------------------------------------------------------------------
# Folder attributes
# ---------------------------------------------------------------------


def _kitsu_entity_for(attribs: Dict[str, Any]) -> Dict[str, Any]:
    """Build the Kitsu entity that mirrors AYON ``attribs``."""
    return {
        "data": {
            "frame_in": attribs["frameStart"],
            "frame_out": attribs["frameEnd"],
            "fps": attribs["fps"],
            "resolution": (
                f"{attribs['resolutionWidth']}x{attribs['resolutionHeight']}"
            ),
            "custom_editorial_key": "editorial_preserve_check",
        },
        "nb_frames": attribs["frameEnd"] - attribs["frameStart"] + 1,
        "description": attribs["description"],
    }


@settings(max_examples=100, deadline=None)
@given(setup=lossless_attrib_setup())
def test_attribute_echo_property(setup: Dict[str, Any]) -> None:
    """Bounded echo for folder attributes; unrelated keys survive."""
    a, b, c = (setup[f"attribs_{k}"] for k in "abc")
    scenario, policy = setup["scenario"], setup["policy"]
    kitsu_curr = {"normal": a, "in_sync": b, "conflict": c}[scenario]

    rig = AttribEchoRig(a, _kitsu_entity_for(kitsu_curr), policy)
    changed = rig.user_changes_attribs(b)
    if scenario == "in_sync" and a == b:
        assert not changed
        return
    assert changed
    assert rig.run_until_quiescent() > 0

    if scenario == "conflict" and policy == "kitsu_wins":
        counts = (0, 1)
    elif scenario == "in_sync":
        counts = (0, 0)
    else:
        counts = (1, 0)
    if scenario == "normal":
        data = rig.kitsu_state["data"]
        assert data["frame_in"] == b["frameStart"]
        assert data["frame_out"] == b["frameEnd"]
        assert rig.kitsu_state["description"] == b["description"]

    data = rig.kitsu_state["data"]
    assert data.get("custom_editorial_key") == "editorial_preserve_check"
    _assert_settled(rig, *counts)


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
def test_attribute_echo_matrix(
    k_fps, prev_fps, new_fps, policy, expected_kw, expected_aw, final_fps
):
    """FPS decision and conflict matrix on production code."""
    rig = AttribEchoRig(
        {"fps": prev_fps},
        {"data": {"fps": k_fps}},
        policy,
    )
    rig.user_changes_attribs({"fps": new_fps})

    rig.run_until_quiescent()

    assert rig.ayon_state["attrib"]["fps"] == final_fps
    assert rig.kitsu_state["data"]["fps"] == final_fps
    _assert_settled(rig, expected_kw, expected_aw)

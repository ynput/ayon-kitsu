"""Property test for assignee update plan (Property 15).

Validates: Requirements 7.1, 7.4, 7.6
"""

# Feature: kitsu-two-way-sync, Property 15: Assignee update plan (Slice 2)

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.mapping import (
    kitsu_person_owner,
    resolve_assignees,
)
from processor.outbound.planning import plan_assignee_update

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@settings(max_examples=100, deadline=None)
@given(
    managed_pool=st.sets(st.uuids().map(str), min_size=0, max_size=15),
    unmanaged_pool=st.sets(st.uuids().map(str), min_size=0, max_size=15),
    data=st.data(),
)
def test_assignee_update_plan_property(managed_pool, unmanaged_pool, data):
    """Property 15: planner preserves unmanaged, matches resolved, sorts."""
    # Ensure disjoint managed and unmanaged sets
    unmanaged = unmanaged_pool - managed_pool
    managed = managed_pool

    # Current Kitsu assignees can draw from both managed and unmanaged
    current_managed = data.draw(
        st.sets(st.sampled_from(sorted(managed)), max_size=len(managed))
        if managed
        else st.just(set())
    )
    current_unmanaged = data.draw(
        st.sets(st.sampled_from(sorted(unmanaged)), max_size=len(unmanaged))
        if unmanaged
        else st.just(set())
    )
    current = current_managed | current_unmanaged

    # Resolved assignees must be a subset of managed (precondition)
    resolved = data.draw(
        st.sets(st.sampled_from(sorted(managed)), max_size=len(managed))
        if managed
        else st.just(set())
    )

    current_ids = list(current)
    resolved_ids = list(resolved)
    managed_ids = list(managed)

    # Copy before call to check non-mutation
    c_copy = list(current_ids)
    r_copy = list(resolved_ids)
    m_copy = list(managed_ids)

    plan = plan_assignee_update(current_ids, resolved_ids, managed_ids)

    # Assert non-mutation
    assert current_ids == c_copy
    assert resolved_ids == r_copy
    assert managed_ids == m_copy

    add_set = set(plan["add"])
    remove_set = set(plan["remove"])

    # add only contains persons that were missing
    assert add_set == resolved - current
    # remove only contains managed persons that were present
    assert remove_set == (current & managed) - resolved
    # persons on both sides appear in neither list
    assert (current & resolved).isdisjoint(add_set)
    assert (current & resolved).isdisjoint(remove_set)
    # unmanaged persons are never removed
    assert remove_set.issubset(managed)

    # outputs are sorted lists
    assert plan["add"] == sorted(plan["add"])
    assert plan["remove"] == sorted(plan["remove"])

    # Applying the plan to current:
    final = (current - remove_set) | add_set
    # Managed part equals resolved set
    assert final & managed == resolved
    # Unmanaged part equals current unmanaged part
    assert final - managed == current - managed

    # Idempotence: planning again against final state yields no changes
    idempotent_plan = plan_assignee_update(
        list(final), resolved_ids, managed_ids
    )
    assert idempotent_plan == {"add": [], "remove": []}

    # Duplicate and permutation invariance:
    permuted_current = list(reversed(current_ids)) + current_ids
    permuted_resolved = list(reversed(resolved_ids)) + resolved_ids
    permuted_managed = list(reversed(managed_ids)) + managed_ids
    permuted_plan = plan_assignee_update(
        permuted_current, permuted_resolved, permuted_managed
    )
    assert permuted_plan == plan


@settings(max_examples=100, deadline=None)
@given(
    unmanaged_ids=st.lists(st.uuids().map(str), min_size=1, max_size=5),
    managed_ids=st.lists(st.uuids().map(str), min_size=0, max_size=5),
)
def test_empty_desired_assignments_preserves_unmanaged(
    unmanaged_ids, managed_ids
):
    """Empty desired assignees clears managed assignees, keeps unmanaged."""
    current_ids = list(set(unmanaged_ids) | set(managed_ids))
    plan = plan_assignee_update(
        current_ids=current_ids,
        resolved_ids=[],
        managed_ids=managed_ids,
    )
    assert plan["add"] == []
    assert set(plan["remove"]) == set(managed_ids) & set(current_ids)
    final = set(current_ids) - set(plan["remove"])
    assert final == set(unmanaged_ids) - set(managed_ids)


@settings(max_examples=100, deadline=None)
@given(
    names=st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                whitelist_characters="_",
            ),
            min_size=1,
            max_size=15,
        ),
        min_size=1,
        max_size=8,
    )
)
def test_resolve_and_owner_composition(names):
    """Composition check: resolved persons have non-None kitsu_person_owner."""
    unique_names = list(set(names))
    ayon_users = [
        {"name": n, "email": f"{n}@example.com"} for n in unique_names
    ]
    kitsu_persons = [
        {"id": f"p-{n}", "email": f"{n}@example.com"} for n in unique_names
    ]

    res = resolve_assignees(names, ayon_users, kitsu_persons)
    for username, person_id in res["resolved"].items():
        person = next(p for p in kitsu_persons if p["id"] == person_id)
        owner = kitsu_person_owner(person, ayon_users)
        assert owner == username

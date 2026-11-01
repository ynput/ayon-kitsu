"""Property test for assignee resolution (Property 14).

Validates: Requirements 7.2, 7.3
"""

# Feature: kitsu-two-way-sync, Property 14: Assignee resolution (Slice 2)

import copy
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.mapping import (
    UNRESOLVED_EMAIL_SEVERAL,
    UNRESOLVED_EMAIL_ZERO,
    UNRESOLVED_KITSU_ID_NOT_FOUND,
    UNRESOLVED_NO_KITSU_ID_NO_EMAIL,
    resolve_assignees,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

VALID_REASONS = {
    UNRESOLVED_NO_KITSU_ID_NO_EMAIL,
    UNRESOLVED_KITSU_ID_NOT_FOUND,
    UNRESOLVED_EMAIL_ZERO,
    UNRESOLVED_EMAIL_SEVERAL,
}


@settings(max_examples=100, deadline=None)
@given(
    uid_a=st.uuids().map(str),
    uid_b=st.uuids().map(str),
    uid_c=st.uuids().map(str),
    uid_d1=st.uuids().map(str),
    uid_d2=st.uuids().map(str),
    stale_kitsu_id=st.uuids().map(str),
    shuffle_seed=st.integers(min_value=0, max_value=1000),
)
def test_assignee_resolution_all_cases(
    uid_a, uid_b, uid_c, uid_d1, uid_d2, stale_kitsu_id, shuffle_seed
):
    """Property 14: resolution follows ID preference, closed reasons, order."""
    # Ensure distinct IDs
    all_ids = {uid_a, uid_b, uid_c, uid_d1, uid_d2, stale_kitsu_id}
    if len(all_ids) < 6:
        return

    # Kitsu persons
    k_person_a = {"id": uid_a, "email": "a@studio.com"}
    k_person_b = {"id": uid_b, "email": "b_fallback@studio.com"}
    k_person_c = {"id": uid_c, "email": "c_unique@studio.com"}
    k_person_d1 = {"id": uid_d1, "email": "d_dup@studio.com"}
    k_person_d2 = {"id": uid_d2, "email": "d_dup@studio.com"}

    kitsu_persons = [
        k_person_a,
        k_person_b,
        k_person_c,
        k_person_d1,
        k_person_d2,
    ]

    # AYON users exercising various alias shapes:
    # 1. user_id_match: valid kitsu_id, also has conflicting email -> ID wins
    user_id_match = {
        "name": "alice",
        "kitsu_id": uid_a,
        "email": "conflicting@studio.com",
    }
    # 2. user_stale_id: stale kitsu_id, email matches k_person_b -> NO fallback
    user_stale_id = {
        "name": "bob",
        "kitsu_id": stale_kitsu_id,
        "email": "b_fallback@studio.com",
    }
    # 3. user_email_unique: no kitsu_id, email matches k_person_c via attrib
    user_email_unique = {
        "name": "charlie",
        "kitsu_id": None,
        "attrib": {"email": "c_unique@studio.com"},
    }
    # 4. user_email_zero: no kitsu_id, email matches 0 Kitsu persons
    user_email_zero = {
        "name": "david",
        "kitsu_id": "",
        "email": "unknown@studio.com",
    }
    # 5. user_email_several: no kitsu_id, email matches 2 Kitsu persons
    user_email_several = {
        "name": "eve",
        "data": {"kitsuId": None},
        "email": "d_dup@studio.com",
    }
    # 6. user_no_id_no_email: neither ID nor email
    user_no_id_no_email = {
        "name": "frank",
        "kitsu_id": None,
        "email": None,
    }

    ayon_users = [
        user_id_match,
        user_stale_id,
        user_email_unique,
        user_email_zero,
        user_email_several,
        user_no_id_no_email,
    ]

    # Query all users plus an unknown username
    requested = [
        "alice",
        "bob",
        "charlie",
        "david",
        "eve",
        "frank",
        "unknown_user",
    ]

    # Copy before call to test non-mutation
    requested_copy = list(requested)
    ayon_copy = copy.deepcopy(ayon_users)
    kitsu_copy = copy.deepcopy(kitsu_persons)

    res = resolve_assignees(requested, ayon_users, kitsu_persons)

    # Assert non-mutation
    assert requested == requested_copy
    assert ayon_users == ayon_copy
    assert kitsu_persons == kitsu_copy

    # Check resolved
    assert res["resolved"] == {
        "alice": uid_a,
        "charlie": uid_c,
    }

    # Check unresolved
    assert res["unresolved"]["bob"] == UNRESOLVED_KITSU_ID_NOT_FOUND
    assert res["unresolved"]["david"] == UNRESOLVED_EMAIL_ZERO
    assert res["unresolved"]["eve"] == UNRESOLVED_EMAIL_SEVERAL
    assert res["unresolved"]["frank"] == UNRESOLVED_NO_KITSU_ID_NO_EMAIL
    assert res["unresolved"]["unknown_user"] == UNRESOLVED_NO_KITSU_ID_NO_EMAIL

    # Assert closed reason set
    for reason in res["unresolved"].values():
        assert reason in VALID_REASONS

    # Test order and duplicate independence:
    # Shuffle and duplicate requested names
    permuted = list(reversed(requested)) + ["alice", "bob", "charlie"]
    res_permuted = resolve_assignees(permuted, ayon_users, kitsu_persons)
    assert res_permuted == res


@settings(max_examples=100, deadline=None)
@given(
    names=st.lists(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"),
                whitelist_characters="_",
            ),
            min_size=1,
            max_size=20,
        ),
        min_size=1,
        max_size=10,
    )
)
def test_assignee_resolution_order_and_deduplication(names):
    """Property 14: order and duplicates do not change resolution output."""
    users = [{"name": n, "email": f"{n}@example.com"} for n in set(names)]
    persons = [
        {"id": f"k-{n}", "email": f"{n}@example.com"} for n in set(names)
    ]

    res1 = resolve_assignees(names, users, persons)
    res2 = resolve_assignees(list(reversed(names)), users, persons)
    res3 = resolve_assignees(names + names, users, persons)

    assert res1 == res2
    assert res1 == res3
    assert set(res1["resolved"].keys()) == set(names)
    assert res1["unresolved"] == {}

"""Property test for assignee round trip (Property 16).

Validates: Requirements 7.5
"""

# Feature: kitsu-two-way-sync, Property 16: Assignee round trip (Slice 2)

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from processor.outbound.inbound_mirror import match_assignees_by_email
from processor.outbound.mapping import (
    UNRESOLVED_KITSU_ID_NOT_FOUND,
    kitsu_person_owner,
    resolve_assignees,
)
from processor.outbound.planning import plan_assignee_update

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


@settings(max_examples=100, deadline=None)
@given(
    target_username=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="_",
        ),
        min_size=1,
        max_size=20,
    ),
    target_email=st.emails(),
    target_person_id=st.uuids().map(str),
    kitsu_id_mode=st.sampled_from(["absent", "matching"]),
    other_count=st.integers(min_value=0, max_value=8),
    data=st.data(),
)
def test_assignee_roundtrip_property(
    target_username,
    target_email,
    target_person_id,
    kitsu_id_mode,
    other_count,
    data,
):
    """Property 16: roundtrip for unique email user returns original name."""
    # Target Kitsu person
    target_person = {
        "id": target_person_id,
        "email": target_email,
        "name": f"Kitsu {target_username}",
    }

    # Target AYON user
    target_kitsu_id = (
        target_person_id if kitsu_id_mode == "matching" else None
    )
    target_user = {
        "name": target_username,
        "email": target_email,
        "kitsu_id": target_kitsu_id,
        "attrib": {"email": target_email},
    }

    # Draw distinct noise records
    noise_emails = data.draw(
        st.sets(st.emails(), min_size=other_count, max_size=other_count)
    )
    assume(target_email not in noise_emails)

    noise_usernames = data.draw(
        st.sets(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"),
                    whitelist_characters="_",
                ),
                min_size=1,
                max_size=20,
            ),
            min_size=other_count,
            max_size=other_count,
        )
    )
    assume(target_username not in noise_usernames)

    noise_person_ids = data.draw(
        st.sets(
            st.uuids().map(str),
            min_size=other_count,
            max_size=other_count,
        )
    )
    assume(target_person_id not in noise_person_ids)

    other_users = []
    other_persons = []
    for n_email, n_user, n_pid in zip(
        noise_emails, noise_usernames, noise_person_ids
    ):
        other_users.append({
            "name": n_user,
            "email": n_email,
            "kitsu_id": None,
            "attrib": {"email": n_email},
        })
        other_persons.append({
            "id": n_pid,
            "email": n_email,
            "name": f"Kitsu {n_user}",
        })

    ayon_users = [target_user] + other_users
    kitsu_persons = [target_person] + other_persons

    # Forward direction: Outbound resolve_assignees
    res = resolve_assignees([target_username], ayon_users, kitsu_persons)
    assert target_username in res["resolved"]
    resolved_person_id = res["resolved"][target_username]
    assert resolved_person_id == target_person_id

    # Retrieve resolved person's email from Kitsu
    person = next(p for p in kitsu_persons if p["id"] == resolved_person_id)
    person_email = person["email"]

    # Reverse direction: Inbound match_assignees_by_email
    matcher_users = [
        {"name": u["name"], "attrib": {"email": u.get("email")}}
        for u in ayon_users
    ]
    roundtrip_names = match_assignees_by_email([person_email], matcher_users)

    assert roundtrip_names == [target_username]


def test_regression_ownership_email_fallback_with_explicit_id():
    """Regression: owner matches person by email even if user has a kitsu_id.

    AYON user alice has kitsu_id='p-a' and email 'same@studio.com'.
    Current Kitsu assignee p-b has id='p-b' and email 'same@studio.com'.
    Inbound matches p-b to alice. Ownership must classify p-b as managed,
    so that an empty desired assignees list plans removal of p-b (7.1, 7.4).
    Simultaneously, outbound resolve_assignees must NOT fall back to email
    for alice because alice has an explicit kitsu_id ('p-a' != 'p-b').
    """
    alice = {
        "name": "alice",
        "kitsu_id": "p-a",
        "email": "same@studio.com",
    }
    person_b = {
        "id": "p-b",
        "email": "same@studio.com",
    }

    # 1. Ownership identifies alice as owner of person_b via email fallback
    owner = kitsu_person_owner(person_b, [alice])
    assert owner == "alice"

    # 2. Because person_b is managed by alice, clearing AYON assignees
    # plans removal of person_b from Kitsu
    plan = plan_assignee_update(
        current_ids=["p-b"],
        resolved_ids=[],
        managed_ids=["p-b"],
    )
    assert plan == {"add": [], "remove": ["p-b"]}

    # 3. Outbound resolve_assignees strictly prohibits email fallback
    # when an explicit kitsu_id is present
    res = resolve_assignees(["alice"], [alice], [person_b])
    assert res["resolved"] == {}
    assert res["unresolved"] == {"alice": UNRESOLVED_KITSU_ID_NOT_FOUND}

"""Hypothesis strategies for the echo property tests."""

from typing import Any, Dict, List, Tuple

from hypothesis import strategies as st

from processor.outbound.mapping import (
    _extract_user_email,
    _extract_user_kitsu_id,
)


def check_user_roundtrip_condition(
    user: Dict[str, Any],
    ayon_users: List[Dict[str, Any]],
    kitsu_persons: List[Dict[str, Any]],
) -> Tuple[bool, str]:
    """Check whether an AYON user satisfies Requirement 7.5 round-trip.

    Conditions from Requirement 7.5:
    1. Email is non-empty string.
    2. Email is unique among AYON users.
    3. Email matches exactly one Kitsu person.
    4. Kitsu_Id is absent or references that same Kitsu person.

    Returns:
        Tuple of (satisfies, reason_if_not).
    """
    if not isinstance(user, dict):
        return False, "invalid_user_dict"

    email = _extract_user_email(user)
    if not email:
        return False, "empty_email"

    matching_ayon = [
        u
        for u in ayon_users
        if isinstance(u, dict) and _extract_user_email(u) == email
    ]
    if len(matching_ayon) != 1:
        return False, f"ayon_email_match_count_{len(matching_ayon)}"

    matching_kitsu = [
        p
        for p in kitsu_persons
        if isinstance(p, dict) and p.get("email") == email
    ]
    if len(matching_kitsu) != 1:
        return False, f"kitsu_email_match_count_{len(matching_kitsu)}"

    kitsu_person = matching_kitsu[0]
    user_kitsu_id = _extract_user_kitsu_id(user)
    if user_kitsu_id is not None and user_kitsu_id != kitsu_person.get("id"):
        return False, "mismatched_kitsu_id"

    return True, "ok"


def count_users_outside_roundtrip_conditions(
    ayon_users: List[Dict[str, Any]],
    kitsu_persons: List[Dict[str, Any]],
) -> int:
    """Count AYON users falling outside Requirement 7.5 round-trip rules."""
    count = 0
    for u in ayon_users:
        ok, _ = check_user_roundtrip_condition(u, ayon_users, kitsu_persons)
        if not ok:
            count += 1
    return count


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

"""Pure mappings between AYON values and Kitsu values for Outbound_Sync.

This module holds the Status_Mapping (Slice 1). The Assignee_Mapping and the
Attribute_Mapping (Slice 2) are added here later, each in its own section.

The module is pure: it imports only the standard library, performs no I/O,
and takes and returns built-in values (``dict``, ``list``, ``str``, ``int``,
``float``, ``bool`` and ``None``).
"""

from __future__ import annotations

import contextlib
import math
from typing import Any


# ---------------------------------------------------------------------------
# Status_Mapping (Requirement 6)
# ---------------------------------------------------------------------------
#
# Inbound_Sync names an AYON status after the Kitsu status ``name`` verbatim:
# ``server/kitsu/anatomy.py`` ``parse_statuses`` builds the anatomy statuses
# with ``name=kitsu_status["name"]``, and the Processor's
# ``utils.get_statuses`` / ``utils.preprocess_task`` set
# ``task["task_status_name"] = statuses[task["task_status_id"]]`` where the
# lookup maps each Kitsu status id to its ``name``. The status list is the
# full ``all_task_statuses()`` set (archived included, F12); archived
# statuses carry ``"archived": True`` in the Zou task-status record.

STATUS_UNMATCHED = "unmatched"
STATUS_AMBIGUOUS = "ambiguous"


def is_archived_status(kitsu_status: dict) -> bool:
    """Tell whether a Kitsu task status is archived.

    Args:
        kitsu_status: A Zou task-status record.

    Returns:
        True when the record's ``archived`` field is truthy. A record without
        the field counts as not archived.
    """
    return bool(kitsu_status.get("archived"))


def map_status(ayon_status: str, kitsu_statuses: list[dict]) -> dict:
    """Map an AYON status name to the Kitsu task status with the same name.

    Matching is an exact, case-sensitive, full-string comparison of
    ``ayon_status`` with each Kitsu status ``name`` (6.2). Archived Kitsu
    statuses are ignored (6.3, 6.7).

    Args:
        ayon_status: The AYON task status name.
        kitsu_statuses: Kitsu task-status records, as returned by
            ``gazu.task.all_task_statuses()`` (the set Inbound_Sync reads).

    Returns:
        ``{"ok": True, "status": {...}}`` with the single matching Kitsu
        status record, or ``{"ok": False, "error": "unmatched",
        "name": ayon_status, "count": 0}`` when no non-archived status
        matches (6.3), or ``{"ok": False, "error": "ambiguous",
        "name": ayon_status, "count": n}`` when ``n > 1`` non-archived
        statuses match (6.7).
    """
    matches = [
        status
        for status in kitsu_statuses
        if not is_archived_status(status)
        and isinstance(status.get("name"), str)
        and status["name"] == ayon_status
    ]
    if len(matches) == 1:
        return {"ok": True, "status": matches[0]}
    return {
        "ok": False,
        "error": STATUS_UNMATCHED if not matches else STATUS_AMBIGUOUS,
        "name": ayon_status,
        "count": len(matches),
    }


def kitsu_status_to_ayon(kitsu_status: dict) -> str:
    """Return the AYON status name Inbound_Sync gives a Kitsu status.

    Inbound_Sync uses the Kitsu status ``name`` unchanged, so mapping a
    non-archived, uniquely named Kitsu status to AYON and back through
    ``map_status`` returns the original Kitsu status id (6.5).

    Args:
        kitsu_status: A Zou task-status record.

    Returns:
        The Kitsu status ``name``.
    """
    return kitsu_status["name"]


# ---------------------------------------------------------------------------
# Assignee_Mapping (Requirement 7, Slice 2)
# ---------------------------------------------------------------------------

UNRESOLVED_NO_KITSU_ID_NO_EMAIL = "no kitsu id and no email"
UNRESOLVED_KITSU_ID_NOT_FOUND = "kitsu id not found"
UNRESOLVED_EMAIL_ZERO = "email matches zero persons"
UNRESOLVED_EMAIL_SEVERAL = "email matches several persons"


def _extract_user_kitsu_id(user: dict) -> str | None:
    """Extract kitsuId from AYON user dict if present as a non-empty string.

    Checks canonical ``kitsu_id`` (from ``/users``), ``kitsuId``, and
    ``data.kitsuId`` (from GraphQL/REST user entities).
    """
    if not isinstance(user, dict):
        return None
    kitsu_id = user.get("kitsu_id")
    if kitsu_id is None:
        kitsu_id = user.get("kitsuId")
    if kitsu_id is None and isinstance(user.get("data"), dict):
        kitsu_id = user["data"].get("kitsuId")
    if isinstance(kitsu_id, str) and kitsu_id != "":
        return kitsu_id
    return None


def _extract_user_email(user: dict) -> str | None:
    """Extract email from AYON user dict if present as a non-empty string.

    Checks canonical ``email`` (from ``/users``) and ``attrib.email``
    (from AYON entity attributes).
    """
    if not isinstance(user, dict):
        return None
    email = user.get("email")
    if email is None and isinstance(user.get("attrib"), dict):
        email = user["attrib"].get("email")
    if isinstance(email, str) and email != "":
        return email
    return None


def resolve_assignees(
    usernames: list[str],
    ayon_users: list[dict],
    kitsu_persons: list[dict],
) -> dict[str, dict[str, str]]:
    """Resolve AYON usernames to Kitsu person IDs (Requirements 7.2, 7.3).

    For each username:
    1. Looks up the AYON user record in ``ayon_users`` by ``name``.
    2. If the user has a Kitsu ID:
       - If a Kitsu person exists with that ID, resolves to that person's ID.
       - Otherwise, records ``"kitsu id not found"``. (Never falls back to
         email when a Kitsu ID is present on the user).
    3. If the user has no Kitsu ID:
       - If the user has no non-empty email, records
         ``"no kitsu id and no email"``.
       - Otherwise, matches against ``kitsu_persons`` by exact, case-sensitive
         email string comparison (mirroring Inbound_Sync matching):
         * Exactly 1 matching person: resolves to that person's ID.
         * 0 matching persons: records ``"email matches zero persons"``.
         * >1 matching persons: records ``"email matches several persons"``.
    4. If the username does not match any AYON user record, records
       ``"no kitsu id and no email"``.

    Duplicate usernames in ``usernames`` are deduplicated, and list order
    does not affect the result (Property 14). When multiple user records in
    ``ayon_users`` share the same username, the last encountered record
    wins (matching standard dictionary iteration).

    Args:
        usernames: List of AYON usernames to resolve.
        ayon_users: List of AYON user records (from ``/users`` or entities).
        kitsu_persons: List of Zou person records (from
            ``gazu.person.all_persons()``).

    Returns:
        Dict with ``resolved`` and ``unresolved`` mappings:
        ``{"resolved": {username: person_id}, "unresolved": {username: ...}}``.
    """
    # Index Kitsu persons
    persons_by_id: dict[str, dict] = {}
    persons_by_email: dict[str, list[dict]] = {}
    for person in kitsu_persons:
        if not isinstance(person, dict):
            continue
        p_id = person.get("id")
        if isinstance(p_id, str) and p_id != "":
            persons_by_id[p_id] = person
        p_email = person.get("email")
        if isinstance(p_email, str) and p_email != "":
            persons_by_email.setdefault(p_email, []).append(person)

    # Index AYON users (last user wins on duplicate username)
    users_by_name: dict[str, dict] = {}
    for u in ayon_users:
        if isinstance(u, dict):
            name = u.get("name")
            if isinstance(name, str) and name != "":
                users_by_name[name] = u

    resolved: dict[str, str] = {}
    unresolved: dict[str, str] = {}

    for username in usernames:
        if not isinstance(username, str) or username == "":
            continue
        if username in resolved or username in unresolved:
            continue

        user = users_by_name.get(username)
        if user is None:
            unresolved[username] = UNRESOLVED_NO_KITSU_ID_NO_EMAIL
            continue

        kitsu_id = _extract_user_kitsu_id(user)
        if kitsu_id is not None:
            if kitsu_id in persons_by_id:
                resolved[username] = kitsu_id
            else:
                unresolved[username] = UNRESOLVED_KITSU_ID_NOT_FOUND
            continue

        # No Kitsu ID: resolve via email
        email = _extract_user_email(user)
        if email is None:
            unresolved[username] = UNRESOLVED_NO_KITSU_ID_NO_EMAIL
            continue

        matches = persons_by_email.get(email, [])
        if len(matches) == 1:
            resolved[username] = matches[0]["id"]
        elif len(matches) == 0:
            unresolved[username] = UNRESOLVED_EMAIL_ZERO
        else:
            unresolved[username] = UNRESOLVED_EMAIL_SEVERAL

    return {"resolved": resolved, "unresolved": unresolved}


def kitsu_person_owner(
    person: dict,
    ayon_users: list[dict],
) -> str | None:
    """Return the AYON username a Kitsu person resolves to (Requirement 7.6).

    Resolution checks:
    1. By Kitsu ID: looks for an AYON user whose Kitsu ID equals
       ``person["id"]``. If multiple users match, the last user wins.
    2. By email: if unlinked by Kitsu ID, looks for an AYON user with an
       exact matching email. Uses ``match_assignees_by_email`` semantics
       ("last user wins").

    Args:
        person: Zou person record.
        ayon_users: List of AYON user records.

    Returns:
        The matched AYON username, or ``None`` when the person is unmanaged.
    """
    if not isinstance(person, dict):
        return None

    p_id = person.get("id")
    if isinstance(p_id, str) and p_id != "":
        # Pass 1: check explicit kitsu_id match (last user wins)
        matched_user: str | None = None
        for u in ayon_users:
            if not isinstance(u, dict):
                continue
            name = u.get("name")
            if not isinstance(name, str) or not name:
                continue
            if _extract_user_kitsu_id(u) == p_id:
                matched_user = name
        if matched_user is not None:
            return matched_user

    # Pass 2: check email match
    p_email = person.get("email")
    if not isinstance(p_email, str) or p_email == "":
        return None

    # Adapt users for match_assignees_by_email (must provide attrib.email)
    eligible_users: list[dict] = []
    for u in ayon_users:
        if not isinstance(u, dict):
            continue
        u_email = _extract_user_email(u)
        name = u.get("name")
        if u_email and name:
            eligible_users.append({
                "name": name,
                "attrib": {"email": u_email},
            })

    from .inbound_mirror import match_assignees_by_email

    matched_names = match_assignees_by_email([p_email], eligible_users)
    if matched_names:
        return matched_names[0]

    return None


# ---------------------------------------------------------------------------
# Attribute_Mapping (Requirement 8, Slice 2)
# ---------------------------------------------------------------------------

MAPPED_ATTRIBUTES = frozenset({
    "fps",
    "frameStart",
    "frameEnd",
    "resolutionWidth",
    "resolutionHeight",
    "description",
})


def ayon_attrib_to_kitsu(attrib: dict) -> dict[str, Any]:
    """Map AYON attributes to Kitsu field paths (Requirement 8.1, 8.2).

    Paths returned:
    - ``fps`` -> ``data.fps`` as float
    - ``resolutionWidth`` & ``resolutionHeight`` -> ``data.resolution`` as
      ``<w>x<h>`` (when both are set)
    - ``frameStart`` & ``frameEnd`` -> ``data.frame_in`` (int),
      ``data.frame_out`` (int), and if ``end >= start``:
      ``nb_frames = end - start + 1``
    - ``description`` -> ``description`` unchanged

    Args:
        attrib: Dict of AYON attribute values.

    Returns:
        Dict of ``{kitsu_field_path: value}``.
    """
    if not isinstance(attrib, dict):
        return {}

    result: dict[str, Any] = {}

    if "fps" in attrib and attrib["fps"] is not None:
        try:
            fps_val = float(attrib["fps"])
            if not (math.isnan(fps_val) or math.isinf(fps_val)):
                result["data.fps"] = fps_val
        except (ValueError, TypeError, OverflowError):
            pass

    has_w = (
        "resolutionWidth" in attrib and attrib["resolutionWidth"] is not None
    )
    has_h = (
        "resolutionHeight" in attrib and attrib["resolutionHeight"] is not None
    )
    if has_w and has_h:
        try:
            w = int(attrib["resolutionWidth"])
            h = int(attrib["resolutionHeight"])
            result["data.resolution"] = f"{w}x{h}"
        except (ValueError, TypeError, OverflowError):
            pass

    has_start = "frameStart" in attrib and attrib["frameStart"] is not None
    has_end = "frameEnd" in attrib and attrib["frameEnd"] is not None

    if has_start and has_end:
        try:
            start = int(attrib["frameStart"])
            end = int(attrib["frameEnd"])
            result["data.frame_in"] = start
            result["data.frame_out"] = end
            if end >= start:
                result["nb_frames"] = end - start + 1
        except (ValueError, TypeError, OverflowError):
            pass
    elif has_start:
        try:
            result["data.frame_in"] = int(attrib["frameStart"])
        except (ValueError, TypeError, OverflowError):
            pass
    elif has_end:
        try:
            result["data.frame_out"] = int(attrib["frameEnd"])
        except (ValueError, TypeError, OverflowError):
            pass

    if "description" in attrib and attrib["description"] is not None:
        result["description"] = attrib["description"]

    return result


def kitsu_attrib_view(
    kitsu_entity: dict, fallback_frame_start: int | None = None
) -> dict[str, Any]:
    """Processor mirror of Inbound parsing for equality checks (5.4).

    Validates Property 8.

    Mirrors push.py caller boundary and attrib_parsing logic:
    1. Reads kitsu_entity['data'] if it is a dict.
    2. Copies data dict (or {} if data is None or not a dict).
    3. If kitsu_entity.get('description') is truthy, sets data['description'].
    4. Calculates end_frame matching end_frame_from_kitsu.
    5. Unconditionally assigns data['frame_out'] = end_frame (even if None).
    6. Parses attributes matching parse_attrib(data).

    Args:
        kitsu_entity: Zou entity dictionary.
        fallback_frame_start: Fallback frame start from parent folder.

    Returns:
        Dict of parsed AYON attributes.
    """
    if not isinstance(kitsu_entity, dict):
        return {}

    raw_data = kitsu_entity.get("data")
    if not isinstance(raw_data, dict):
        data: dict = {}
    else:
        data = dict(raw_data)

    if "description" in kitsu_entity:
        data["description"] = kitsu_entity["description"] or ""

    # Calculate end frame mirroring end_frame_from_kitsu
    end_frame = None
    if isinstance(raw_data, dict):
        if raw_data.get("frame_out"):
            end_frame = raw_data.get("frame_out")
        elif kitsu_entity.get("nb_frames") and not raw_data.get("frame_out"):
            frame_start = raw_data.get("frame_in")
            if frame_start is None:
                frame_start = fallback_frame_start
            if frame_start is not None:
                try:
                    end_frame = (
                        int(frame_start) + int(kitsu_entity["nb_frames"]) - 1
                    )
                except (ValueError, TypeError):
                    end_frame = None

    data["frame_out"] = end_frame

    # Parse attributes mirroring parse_attrib verbatim
    result: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        if key == "fps":
            with contextlib.suppress(ValueError):
                result["fps"] = float(value)
        elif key == "frame_in":
            with contextlib.suppress(ValueError):
                result["frameStart"] = int(value)
        elif key == "frame_out":
            with contextlib.suppress(ValueError):
                result["frameEnd"] = int(value)
        elif key == "resolution" and value:
            try:
                parts = value.split("x")
                result["resolutionWidth"] = int(parts[0])
                result["resolutionHeight"] = int(parts[1])
            except (IndexError, ValueError):
                pass
        elif key == "description":
            result["description"] = value
        elif key == "start_date" and value:
            result["startDate"] = value + "T00:00:00Z"
        elif key == "end_date" and value:
            result["endDate"] = value + "T00:00:00Z"

    return result



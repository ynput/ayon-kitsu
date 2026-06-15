"""Utils shared between fullsync.py and update_from_kitsu.py."""

import re
import unicodedata
from typing import Any

import ayon_api
import gazu


def get_asset_types(kitsu_project_id: str) -> dict[str, str]:
    raw_asset_types = gazu.asset.all_asset_types_for_project(kitsu_project_id)
    kitsu_asset_types = {}
    for asset_type in raw_asset_types:
        kitsu_asset_types[asset_type["id"]] = asset_type["name"]
    return kitsu_asset_types


def get_task_types(kitsu_project_id: str) -> dict[str, str]:
    raw_task_types = gazu.task.all_task_types_for_project(kitsu_project_id)
    kitsu_task_types = {}
    for task_type in raw_task_types:
        kitsu_task_types[task_type["id"]] = task_type["name"]
    return kitsu_task_types


def get_statuses() -> dict[str, str]:
    raw_statuses = gazu.task.all_task_statuses()
    kitsu_statuses = {}
    for status in raw_statuses:
        kitsu_statuses[status["id"]] = status["name"]
    return kitsu_statuses


def preprocess_asset(
    kitsu_project_id: str,
    asset: dict[str, str],
    asset_types: dict[str, str] = {},
) -> dict[str, str]:
    if not asset_types:
        asset_types = get_asset_types(kitsu_project_id)

    if "entity_type_id" in asset and asset["entity_type_id"] in asset_types:
        asset["asset_type_name"] = asset_types[asset["entity_type_id"]]
    return asset


def preprocess_task(
    kitsu_project_id: str,
    task: dict[str, str | list[str]],
    task_types: dict[str, str | list[str]] = {},
    statuses: dict[str, str] = {},
) -> dict[str, str | list[str]]:
    if not task_types:
        task_types = get_task_types(kitsu_project_id)

    if not statuses:
        statuses = get_statuses()

    if "task_type_id" in task and task["task_type_id"] in task_types:
        task["task_type_name"] = task_types[task["task_type_id"]]

    if "task_status_id" in task and task["task_status_id"] in statuses:
        task["task_status_name"] = statuses[task["task_status_id"]]

    if "name" in task and "task_type_name" in task and task["name"] == "main":
        task["name"] = task["task_type_name"].lower()

    # Match the assigned ayon user with the assigned kitsu email
    ayon_users = {
        user["attrib"]["email"]: user["name"] for user in ayon_api.get_users()
    }
    task_emails = {user["email"] for user in task["persons"]}
    task["assignees"] = []
    task["assignees"].extend(
        ayon_users[email] for email in task_emails if email in ayon_users
    )

    return task


def _remove_accents(s: str) -> str:
    """Strip diacritics and normalize special characters for AYON usernames.
    
    Args:
        s: The string to remove accents from.

    Returns:
        The string with accents removed.
    """
    nfkd = unicodedata.normalize("NFKD", s)
    result = "".join(c for c in nfkd if not unicodedata.combining(c))
    replacement_map = {
        "Æ": "AE", "Ð": "D", "Ø": "O", "Þ": "TH",
        "ß": "ss", "æ": "ae", "ð": "d", "ø": "o", "þ": "th",
        "Œ": "OE", "œ": "oe", "ƒ": "f",
    }
    for k, v in replacement_map.items():
        result = result.replace(k, v)
    return re.sub(r"[^a-zA-Z0-9_\.\-]", "", result)


def _to_entity_name(name: str) -> str:
    """Sanitize a string into a valid AYON entity name.

    Args:
        name: The string to sanitize.

    Returns:
        The sanitized string.
    """
    name = name.strip()
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^a-zA-Z0-9_\.\-]", "", name)
    name = re.sub(r"^[^a-zA-Z0-9_]+", "", name)
    name = re.sub(r"[^a-zA-Z0-9_]+$", "", name)
    return name


def to_username(first_name: str, last_name: str | None = None) -> str:
    """Derive an AYON username from Kitsu first and last name.

    Mirrors ``server/kitsu/addon_helpers.to_username``; duplicated here because
    the processor is deployed separately from the addon server.

    Args:
        first_name: The first name of the person.
        last_name: The last name of the person.

    Returns:
        The derived username.
    """
    name = (
        f"{first_name.strip()}.{last_name.strip()}"
        if last_name
        else first_name.strip()
    )
    return _to_entity_name(_remove_accents(name.lower()))


def get_ayon_user_sync_info(entrypoint: str) -> list[dict[str, Any]]:
    """Fetch the AYON user list from the addon's /users endpoint.

    Returns one dict per user with keys: ``name``, ``kitsu_id``, ``email``,
    ``full_name``.  The server queries the DB directly so ``kitsu_id`` is
    available (the GraphQL ``UserNode`` schema does not expose ``data``).

    Args:
        entrypoint: Base addon REST path, e.g. ``/addons/kitsu/1.2.7``.
    """
    response = ayon_api.get(f"{entrypoint}/users")
    response.raise_for_status()
    return response.data


def build_ayon_user_lookups(
    users: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build lookup tables from the user sync-info list.

    Args:
        users: List of user dicts as returned by :func:`get_ayon_user_sync_info`.

    Returns:
        Three dicts keyed by kitsu_id, email, and AYON username respectively.
    """
    by_kitsu_id: dict[str, Any] = {}
    by_email: dict[str, Any] = {}
    by_name: dict[str, Any] = {}
    for u in users:
        if u.get("kitsu_id"):
            by_kitsu_id[u["kitsu_id"]] = u
        if u.get("email"):
            by_email[u["email"]] = u
        if u.get("name"):
            by_name[u["name"]] = u
    return by_kitsu_id, by_email, by_name


def person_needs_sync(
    person: dict[str, Any],
    ayon_users_by_kitsu_id: dict[str, Any],
    ayon_users_by_email: dict[str, Any],
    ayon_users_by_name: dict[str, Any],
) -> bool:
    """Return whether a Kitsu person should be pushed to AYON.

    Matching priority:
    1. ``kitsuId`` — the canonical link once a user has been synced at least once.
    2. Email — fallback for users synced before kitsuId tracking.
    3. Derived username — if a username-only match is found, it means
       this is a duplicate Kitsu account for the same AYON user and is skipped.

    A matched user is considered up-to-date when its ``fullName`` matches
    ``person["full_name"]``.  Derived username is intentionally not compared
    because renaming AYON users can have side effects.

    Args:
        person: Kitsu person dict (from ``gazu.person.all_persons()``).
        ayon_users_by_kitsu_id: Lookup keyed by kitsu_id.
        ayon_users_by_email: Lookup keyed by email.
        ayon_users_by_name: Lookup keyed by AYON username.

    Returns:
        ``True`` if the person should be pushed to AYON, ``False`` to skip.
    """
    kitsu_id = person.get("id", "")
    email = person.get("email", "")
    username = to_username(
        person.get("first_name", ""),
        person.get("last_name") or None,
    )

    id_match_ayon_user = ayon_users_by_kitsu_id.get(kitsu_id)
    email_match_ayon_user = ayon_users_by_email.get(email)
    existing_ayon_user = id_match_ayon_user or email_match_ayon_user or ayon_users_by_name.get(username)

    if not existing_ayon_user:
        return True
    elif not id_match_ayon_user and not email_match_ayon_user:
        # Username-only match — duplicate Kitsu account, always skip.
        # i.e two "John Doe" (username `john.doe`) users with different emails.
        return False

    return (
        existing_ayon_user.get("full_name") != person.get("full_name")
        or existing_ayon_user.get("active") != person.get("active")
        or existing_ayon_user.get("email") != person.get("email", "")
    )


def get_persons(entrypoint: str) -> list[dict]:
    """Return Kitsu persons that are new or changed compared to AYON users.

    Args:
        entrypoint: Base addon REST path forwarded to :func:`get_ayon_user_sync_info`.
    """
    users = get_ayon_user_sync_info(entrypoint)
    by_kitsu_id, by_email, by_name = build_ayon_user_lookups(users)
    return [
        person
        for person in gazu.person.all_persons()
        if person_needs_sync(person, by_kitsu_id, by_email, by_name)
    ]

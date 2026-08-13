"""Utils shared between fullsync.py and update_from_kitsu.py."""

import re
import unicodedata
from typing import Iterable, Optional, Any

import ayon_api
import gazu
from nxtools import logging, slugify


def get_ayon_folders_by_kitsu_ids(
    project_name: str,
    kitsu_ids: set[str],
    folder_types: Optional[Iterable[str]] = None,
) -> dict[str, dict]:
    """Find AYON folders by their stored Kitsu ids.

    Args:
        project_name (str): The name of the AYON project.
        kitsu_ids (set[str]): Kitsu ids of the folders to find.
        folder_types (Optional[Iterable[str]]): Folder types to filter by.

    Returns:
        dict[str, dict]: Mapping of kitsuId -> AYON folder dict for found ids.
    """
    result: dict[str, dict] = {}
    for folder in ayon_api.get_folders(
        project_name,
        folder_types=folder_types,
        fields={"id", "name", "parentId", "folderType", "data"},
    ):
        folder_kitsu_id = (folder.get("data") or {}).get("kitsuId")
        if folder_kitsu_id in kitsu_ids:
            result[folder_kitsu_id] = folder

            # Stop if we have found all the folders we need
            if len(result) == len(kitsu_ids):
                break
    return result


def _ensure_asset_type_folder(
    project_name: str,
    entity_type_id: str,
    asset_type_name: str,
    folders_by_kitsu_id: dict[str, dict],
) -> str | None:
    """Return the AYON folder id for an asset type, creating it if needed.

    Args:
        project_name (str): The name of the AYON project.
        entity_type_id (str): The Kitsu entity type id.
        asset_type_name (str): The name of the asset type.
        folders_by_kitsu_id (dict): A dictionary of AYON folders by Kitsu id.

    Returns:
        str: The AYON folder id for the asset type.
    """
    asset_type_folder = folders_by_kitsu_id.get(entity_type_id)
    if asset_type_folder:
        return asset_type_folder["id"]

    assets_root = folders_by_kitsu_id.get("asset")
    if not assets_root:
        # Create the Assets folder if it doesn't exist
        assets_root_id = ayon_api.create_folder(
            project_name,
            name="Assets",
            data={"kitsuId": "asset"},
        )
        folders_by_kitsu_id["asset"] = {"id": assets_root_id}
    else:
        assets_root_id = assets_root["id"]

    asset_type_folder_id = ayon_api.create_folder(
        project_name,
        name=slugify(asset_type_name, separator="_"),
        label=asset_type_name,
        parent_id=assets_root_id,
        data={"kitsuId": entity_type_id},
    )
    folders_by_kitsu_id[entity_type_id] = {"id": asset_type_folder_id}
    return asset_type_folder_id


def move_folders_by_asset_type(
    project_name: str, entities: list[dict[str, Any]]
) -> None:
    """Re-parent AYON asset folders when their Kitsu asset type differs.

    Skip moves for folders that already have published products. Leave old
    asset-type folders in place even if they become empty.

    Args:
        project_name (str): The name of the AYON project.
        entities (list[dict[str, Any]]): List of kitsu entities to process.
    """
    entities_ids: set[str] = {"asset"}
    for entity in entities:
        if entity.get("id"):
            entities_ids.add(entity["id"])
        if entity.get("entity_type_id"):
            entities_ids.add(entity["entity_type_id"])

    folders_by_kitsu_id = get_ayon_folders_by_kitsu_ids(
        project_name, entities_ids
    )

    folders_to_move: list[tuple[dict[str, Any], dict, str]] = []
    for entity in entities:
        entity_type_id = entity.get("entity_type_id")
        asset_type_name = entity.get("asset_type_name")

        if not entity_type_id or not asset_type_name:
            # Asset type couldn't be resolved (e.g. brand new asset type
            # not yet cached) - nothing to re-parent, skip safely.
            logging.warning(
                f"Cannot move asset {entity.get('name')}: "
                "missing entity_type_id/asset_type_name on entity"
            )
            continue

        asset_folder = folders_by_kitsu_id.get(entity.get("id"))
        if not asset_folder:
            # The folder may not have been indexed yet (e.g. it was just
            # created by the /push call). Skip it instead of crashing -
            # it will be re-parented on the next sync if still needed.
            logging.warning(
                f"Cannot move asset {entity.get('name')}: "
                "folder not found in AYON"
            )
            continue

        desired_parent_id = _ensure_asset_type_folder(
            project_name,
            entity_type_id,
            asset_type_name,
            folders_by_kitsu_id,
        )
        if not desired_parent_id:
            logging.warning(
                f"Cannot move asset {entity.get('name')}: "
                "failed to resolve asset type folder"
            )
            continue

        if asset_folder.get("parentId") == desired_parent_id:
            continue

        folders_to_move.append((entity, asset_folder, desired_parent_id))

    if not folders_to_move:
        return

    folder_ids_with_products = {
        product["folderId"]
        for product in ayon_api.get_products(
            project_name,
            folder_ids=[
                asset_folder["id"] for _, asset_folder, _ in folders_to_move
            ],
            fields={"folderId"},
        )
    }

    for entity, asset_folder, desired_parent_id in folders_to_move:
        if asset_folder["id"] in folder_ids_with_products:
            logging.warning(
                f"Skipping move of asset '{entity.get('name')}' to "
                f"'{entity.get('asset_type_name')}': "
                "folder has published products"
            )
            continue

        logging.info(
            f"Moving asset '{entity.get('name')}' to asset type "
            f"'{entity.get('asset_type_name')}'"
        )
        ayon_api.update_folder(
            project_name,
            asset_folder["id"],
            parent_id=desired_parent_id,
        )


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
        "Æ": "AE",
        "Ð": "D",
        "Ø": "O",
        "Þ": "TH",
        "ß": "ss",
        "æ": "ae",
        "ð": "d",
        "ø": "o",
        "þ": "th",
        "Œ": "OE",
        "œ": "oe",
        "ƒ": "f",
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
        users: List of user dicts as returned by
            :func:`get_ayon_user_sync_info`.

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
    1. ``kitsuId`` — canonical link once a user has been synced at least once.
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
    name_match_ayon_user = ayon_users_by_name.get(username)
    existing_ayon_user = (
        id_match_ayon_user or email_match_ayon_user or name_match_ayon_user
    )

    if not existing_ayon_user:
        return True

    # Backfill kitsu_id on legacy users matched by email/username.
    if not id_match_ayon_user and not existing_ayon_user.get("kitsu_id"):
        return True

    if (
        name_match_ayon_user
        and not id_match_ayon_user
        and not email_match_ayon_user
    ):
        # Username-only match with already-linked user: duplicate Kitsu account
        return False

    return (
        existing_ayon_user.get("full_name") != person.get("full_name")
        or existing_ayon_user.get("active") != person.get("active")
        or existing_ayon_user.get("email") != person.get("email", "")
    )


def get_persons_to_update(entrypoint: str) -> list[dict]:
    """Return Kitsu persons that are new or changed compared to AYON users.

    Args:
        entrypoint: REST forwarded to :func:`get_ayon_user_sync_info`.
    """
    users = get_ayon_user_sync_info(entrypoint)
    by_kitsu_id, by_email, by_name = build_ayon_user_lookups(users)
    return [
        person
        for person in gazu.person.all_persons()
        if person_needs_sync(person, by_kitsu_id, by_email, by_name)
    ]

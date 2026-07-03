""" utils shared between fullsync.py and update_from_kitsu.py """

from typing import Iterable, Optional

import ayon_api
import gazu


def get_ayon_folders_by_kitsu_ids(
    project_name: str,
    kitsu_ids: set[str],
    folder_types: Optional[Iterable[str]] = None,
) -> dict[str, dict]:
    """Find AYON folders by their stored Kitsu ids.

    Args:
        project_name: The name of the AYON project.
        kitsu_ids: Kitsu ids of the folders to find.
        folder_types: An optional iterable of folder types to filter by.

    Returns:
        Mapping of kitsuId -> AYON folder dict for ids that were found.
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

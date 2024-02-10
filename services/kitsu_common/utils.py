import contextlib
from typing import TYPE_CHECKING, Any

import gazu
from nxtools import logging, slugify

if TYPE_CHECKING:
    import ayon_api
    from ayon_api.entity_hub import BaseEntity, EntityHub, FolderEntity, ProjectEntity


class KitsuServerError(Exception):
    pass


class KitsuSettingsError(Exception):
    pass


def create_short_name(name: str) -> str:
    code = name.lower()

    if "_" in code:
        subwords = code.split("_")
        code = "".join([subword[0] for subword in subwords])[:4]
    elif len(name) > 4:
        vowels = ["a", "e", "i", "o", "u"]
        filtered_word = "".join([char for char in code if char not in vowels])
        code = filtered_word[:4]

    # if there is a number at the end of the code, add it to the code
    last_char = code[-1]
    if last_char.isdigit():
        code += last_char

    return code


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


def get_kitsu_credentials(
    ayon_api: "ayon_api",
    settings: dict[str, str],
) -> tuple[str, str, str]:
    """Gets the kitsu credentials from Ayon

    Args:
        ayon_api (ayon_api): The initialized ayon API instance
        settings (dict[str, str]): Your services addon settings

    Returns:
        list[str]: The Kitsu credentials
    """
    try:
        kitsu_server_url = settings.get("server").rstrip("/") + "/api"

        email_sercret = settings.get("login_email")
        password_secret = settings.get("login_password")

        assert email_sercret, f"Email secret `{email_sercret}` not set"
        assert password_secret, f"Password secret `{password_secret}` not set"

        kitsu_login_email = None
        kitsu_login_password = None
        try:
            kitsu_login_email = ayon_api.get_secret(email_sercret)["value"]
            kitsu_login_password = ayon_api.get_secret(password_secret)["value"]
        except KeyError as e:
            raise KitsuSettingsError(f"Secret `{e}` not found") from e

        assert kitsu_login_password, "Kitsu password not set"
        assert kitsu_server_url, "Kitsu server not set"
        assert kitsu_login_email, "Kitsu email not set"

        return (
            kitsu_server_url,
            kitsu_login_email,
            kitsu_login_password,
        )
    except AssertionError as e:
        logging.error(f"KitsuProcessor failed to initialize: {e}")
        raise KitsuSettingsError() from e


def parse_attrib(source: dict[str, Any] | None = None) -> dict[str, str | int | float]:
    result: dict[str, str | int | float] = {}
    if source is None:
        return result
    for key, value in source.items():
        if value is None:
            continue
        # Slugify the key as the key might come from custom metadata from Kitsu
        key = slugify(key)
        if key == "fps":
            with contextlib.suppress(ValueError):
                result["fps"] = float(value)
        elif key == "frame_in":
            with contextlib.suppress(ValueError):
                result["frameStart"] = int(value)
        elif key == "frame_out":
            with contextlib.suppress(ValueError):
                result["frameEnd"] = int(value)
        elif key == "nb_frames":
            with contextlib.suppress(ValueError):
                result["frames"] = int(value)
        elif key == "resolution":
            try:
                result["resolutionWidth"] = int(value.split("x")[0])
                result["resolutionHeight"] = int(value.split("x")[1])
            except (IndexError, ValueError):
                pass
        elif key == "description":
            result["description"] = value
        elif key == "start_date":
            result["startDate"] = value + "T00:00:00Z"
        elif key == "end_date":
            result["endDate"] = value + "T00:00:00Z"
        elif key == "data":
            # there might exist custom metadata
            result = result | parse_attrib(value)

    return result


def get_or_create_root_folder_by_name(
    ay_project: "EntityHub",
    folder_name: str,
    folder_type: str = "Folder",
):
    root = ay_project.get_entity_children(ay_project.project_entity)
    for folder in root:
        if folder.name == folder_name:
            return folder

    return ay_project.add_new_folder(
        folder_type=folder_type,
        name=folder_name,
    )


def scan_for_entity_by_kitsu_id(
    kitsu_id: str,
    root: "BaseEntity",
):
    if root.data.get("kitsuId") == kitsu_id:
        return root
    if root.entity_type == "folder":
        for child in root.children:
            result = scan_for_entity_by_kitsu_id(kitsu_id, child)
            if result:
                return result


def get_entity_by_kitsu_id(
    kitsu_id: str,
    ay_project: "EntityHub",
):
    root: list["FolderEntity"] = ay_project.get_entity_children(
        ay_project.project_entity
    )
    for child in root:
        result = scan_for_entity_by_kitsu_id(kitsu_id, child)
        if result:
            return result


def get_task_type_short_name_by_task_name(name: str, project_entity: "ProjectEntity"):
    tasks = project_entity.get_task_types()
    for task in tasks:
        if task["name"] == name:
            return task["shortName"]

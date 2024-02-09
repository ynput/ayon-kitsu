from typing import TYPE_CHECKING

import gazu
from nxtools import logging

from .constants import kitsu_models, kitsu_statuses, kitsu_tasks

if TYPE_CHECKING:
    import ayon_api
    from ayon_api.entity_hub import ProjectEntity


class KitsuServerError(Exception):
    pass


class KitsuSettingsError(Exception):
    pass


def create_short_name(project_name: str) -> str:
    project_name = project_name.lower()
    code = project_name

    if "_" in project_name:
        subwords = project_name.split("_")
        code = "".join([subword[0] for subword in subwords])[:4]
    elif len(project_name) > 4:
        vowels = ["a", "e", "i", "o", "u"]
        filtered_word = "".join([char for char in project_name if char not in vowels])
        code = filtered_word[:4]

    # if there is a number at the end of the project_name, add it to the code
    last_char = project_name[-1]
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


def create_kitsu_entities_in_ay(
    project_entity: "ProjectEntity",
    kitsu_project: dict[str, str],
):
    """Ensure Ayon has all the Kitsu entitys, task types and statuses.

    Args:
        project_entity (ProjectEntity): The ProjectEntity for a given project.
        kitsu_project (dict): The project owning the Tasks.
    """

    # Add Kitsu models as folder types to Project Entity
    project_entity.set_folder_types(project_entity.get_folder_types() + kitsu_models)

    ## Add Project task types to Project Entity
    task_types = []

    default_types = project_entity.get_task_types()
    kitsu_types = gazu.task.all_task_types_for_project(kitsu_project)

    for kitsu_type in kitsu_types:
        new_type = {}
        new_type["name"] = kitsu_type["name"]
        # Fetch data from Ayon defaults
        for default_type in default_types:
            if new_type["name"] == default_type["name"]:
                new_type["icon"] = default_type["icon"]
                new_type["shortName"] = default_type["shortName"]

        # Fetch icon from constants
        constant_type = kitsu_tasks.get(new_type["name"].lower())
        if constant_type:
            new_type["icon"] = constant_type["icon"]

        # Generate short name
        if "shortName" not in new_type:
            new_type["shortName"] = create_short_name(new_type["name"])
        task_types.append(new_type)
    project_entity.set_task_types(task_types)

    # Add Kitsu task statuses to Project Entity
    project_entity.set_statuses(gazu.task.all_task_statuses_for_project(kitsu_project))
    # Add state and icon to the statuses
    for status in project_entity.get_statuses():
        kitsu_status = kitsu_statuses.get(status.short_name)
        if kitsu_status:
            status.set_icon(kitsu_status["icon"])
            status.set_state(kitsu_status["state"])

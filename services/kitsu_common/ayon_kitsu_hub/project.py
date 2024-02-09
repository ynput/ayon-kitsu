from typing import TYPE_CHECKING, Any
import ayon_api

import gazu

from kitsu_common.constants import kitsu_models, kitsu_statuses, kitsu_tasks
from kitsu_common.utils import create_short_name

if TYPE_CHECKING:
    from ayon_api.entity_hub import EntityHub, ProjectEntity


def parse_attrib(source: dict[str, Any] | None = None):
    result = {}
    if source is None:
        return result
    for key, value in source.items():
        if key == "fps":
            result["fps"] = float(value)
        elif key == "frame_in":
            result["frameStart"] = int(value)
        elif key == "frame_out":
            result["frameEnd"] = int(value)
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

    return result


def kitsu_project_create(
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
        new_type["id"] = kitsu_type["id"]
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


def kitsu_project_update(
    kitsu_project: dict[str, str | None],
    ay_project: "EntityHub",
):
    attribs = parse_attrib(kitsu_project)
    for key, value in attribs.items():
        ay_project.project_entity.attribs.set(key, value)


def kitsu_project_delete(
    ay_project: "EntityHub",
):
    ayon_api.delete_project(ay_project.project_name)

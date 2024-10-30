import contextlib
from typing import TYPE_CHECKING, Any

from nxtools import logging

from ayon_server.entities import ProjectEntity
from ayon_server.exceptions import AyonException
from ayon_server.lib.postgres import Postgres
from ayon_server.settings.anatomy import Anatomy
from ayon_server.settings.anatomy.statuses import Status
from ayon_server.settings.anatomy.task_types import TaskType

from .addon_helpers import create_short_name, remove_accents
from .extract_ayon_project_anatomy import extract_ayon_project_anatomy

if TYPE_CHECKING:
    from .. import KitsuAddon

async def parse_task_types(
    addon: "KitsuAddon", kitsu_project_id: str
) -> list[TaskType]:
    """

    Kitsy structure:

    {
      "name": "Lookdev",
      "short_name": "",
      "color": "#64B5F6",
      "priority": 3,
      "for_entity": "Asset",
      "allow_timelog": true,
      "archived": false,
      "shotgun_id": null,
      "department_id": "3730aeca-1911-483b-819d-79afd99c984b",
      "id": "ff41528d-4a3c-4e09-ae88-b879047a5104",
      "created_at": "2023-06-21T19:02:07",
      "updated_at": "2023-06-28T14:49:45",
      "type": "TaskType"
    }

    Ayon structure:

    name:
    shortName:
    icon:

    """

    task_status_response = await addon.kitsu.get(
        f"data/projects/{kitsu_project_id}/task-types"
    )
    if task_status_response.status_code != 200:
        raise AyonException("Could not get Kitsu task types")
    result: list[TaskType] = []
    for kitsu_task_type in task_status_response.json():
        # Check if the task already exist
        # eg. Concept under Assets and the hardcoded Concept under Concepts
        if any(d.name == kitsu_task_type["name"] for d in result):
            continue

        short_name = None
        icon = None

        settings = await addon.get_studio_settings()
        found = False
        for task in settings.sync_settings.default_sync_info.default_task_info:
            if task.name.lower() == kitsu_task_type["name"].lower():
                found = True
                short_name = task.short_name
                icon = task.icon

        if not found:
            short_name = kitsu_task_type.get("short_name")
            if not short_name:
                name_slug = remove_accents(kitsu_task_type["name"].lower())
                short_name = create_short_name(name_slug)
            icon = "task_alt"

        result.append(
            TaskType(
                name=kitsu_task_type["name"],
                shortName=short_name,
                icon=icon,
            )
        )

    return result


async def parse_statuses(
    addon: "KitsuAddon", kitsu_project_id: str
) -> list[Status]:
    """Map kitsu status to ayon status

    Kitsu structure:

      {
        "name": "Retake",
        "archived": false,
        "short_name": "retake",
        "color": "#ff3860",
        "is_done": false,
        "is_artist_allowed": true,
        "is_client_allowed": true,
        "is_retake": true,
        "is_feedback_request": false,
        "is_default": false,
        "shotgun_id": null,
        "id": "500acc0f-2355-44b1-9cde-759287084c05",
        "created_at": "2023-06-21T19:02:07",
        "updated_at": "2023-06-21T19:02:07",
        "type": "TaskStatus"
      },

    Ayon structure:

        name
        shortName
        state: Literal["not_started", "in_progress", "done", "blocked"]
        icon
        color

    """

    task_status_response = await addon.kitsu.get("data/task-status")
    if task_status_response.status_code != 200:
        raise AyonException("Could not get Kitsu statuses")

    result: list[Status] = []
    kitsu_statuses = task_status_response.json()
    kitsu_statuses.sort(key=lambda x: not x.get("is_default"))
    settings = await addon.get_studio_settings()

    for status in kitsu_statuses:
        found = False
        for (
            settings_status
        ) in settings.sync_settings.default_sync_info.default_status_info:
            if status["short_name"] == settings_status.short_name:
                found = True
                status["icon"] = settings_status.icon
                status["state"] = settings_status.state
        if not found:
            status["icon"] = "task_alt"
            status["state"] = "in_progress"

    for kitsu_status in kitsu_statuses:
        status = Status(
            name=kitsu_status["name"],
            shortName=kitsu_status["short_name"],
            color=kitsu_status["color"],
            state=kitsu_status["state"],
            icon=kitsu_status["icon"],
        )
        result.append(status)
    return result


#
# Load kitsu project and create ayon anatomy object
#


def parse_attrib(source: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {}
    if source is None:
        return result
    for key, value in source.items():
        if key == "fps" and value:
            with contextlib.suppress(ValueError):
                result["fps"] = float(value)
        elif key == "frame_in" and value:
            with contextlib.suppress(ValueError):
                result["frameStart"] = int(value)
        elif key == "frame_out" and value:
            with contextlib.suppress(ValueError):
                result["frameEnd"] = int(value)
        elif key == "resolution" and value:
            try:
                result["resolutionWidth"] = int(value.split("x")[0])
                result["resolutionHeight"] = int(value.split("x")[1])
            except (IndexError, ValueError):
                pass
        elif key == "description" and value:
            result["description"] = value
        elif key == "start_date" and value:
            result["startDate"] = value + "T00:00:00Z"
        elif key == "end_date" and value:
            result["endDate"] = value + "T00:00:00Z"

    return result


async def get_primary_anatomy_preset() -> Anatomy:
    query = "SELECT * FROM anatomy_presets WHERE is_primary is TRUE"
    async for row in Postgres.iterate(query):
        return Anatomy(**row["data"])
    return Anatomy()


async def get_kitsu_project_anatomy(
    addon: "KitsuAddon",
    kitsu_project_id: str,
    ayon_project: ProjectEntity | None = None,
) -> Anatomy:
    kitsu_project_response = await addon.kitsu.get(
        f"data/projects/{kitsu_project_id}"
    )
    if kitsu_project_response.status_code != 200:
        raise AyonException("Could not get Kitsu project")

    kitsu_project = kitsu_project_response.json()

    attributes = parse_attrib(kitsu_project)
    statuses = await parse_statuses(addon, kitsu_project_id)
    task_types = await parse_task_types(addon, kitsu_project_id)

    if ayon_project:
        anatomy = extract_ayon_project_anatomy(ayon_project)
    else:
        anatomy = await get_primary_anatomy_preset()

    anatomy_dict = anatomy.dict()
    for key in anatomy_dict["attributes"]:
        if key in attributes:
            anatomy_dict["attributes"][key] = attributes[key]
            logging.debug("updated project", ayon_project.name, "anatomy attribute", key, "to", attributes[key])


    anatomy_dict["statuses"] = statuses
    anatomy_dict["task_types"] = task_types

    return Anatomy(**anatomy_dict)

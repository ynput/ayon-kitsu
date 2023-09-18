from typing import TYPE_CHECKING

from ayon_server.exceptions import AyonException
from ayon_server.settings.anatomy import Anatomy
from ayon_server.settings.anatomy.statuses import Status
from ayon_server.settings.anatomy.task_types import TaskType, default_task_types

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
        name_slug = kitsu_task_type["name"].lower()

        # Use ayon default task type if it exists

        for default_task_type in default_task_types:
            if default_task_type.name.lower() == name_slug:
                result.append(default_task_type)
                break
        else:
            result.append(
                TaskType(
                    name=kitsu_task_type["name"],
                    shortName=kitsu_task_type["short_name"],
                )
            )

    return result


async def parse_statuses(addon: "KitsuAddon", kitsu_project_id: str) -> list[Status]:
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

    task_status_response = await addon.kitsu.get(
        f"data/projects/{kitsu_project_id}/settings/task-status"
    )
    if task_status_response.status_code != 200:
        raise AyonException("Could not get Kitsu statuses")

    def get_state(kitsu_status: dict[str, str]) -> str:
        if kitsu_status["is_done"]:
            return "done"
        elif kitsu_status["short_name"] == "ready":
            return "not_started"
        else:
            return "in_progress"

    result: list[Status] = []
    for kitsu_status in task_status_response.json():
        status = Status(
            name=kitsu_status["name"],
            shortName=kitsu_status["short_name"],
            color=kitsu_status["color"],
            state=get_state(kitsu_status),
        )
        result.append(status)
    return result


#
# Load kitsu project and create ayon anatomy object
#

async def get_kitsu_project_anatomy(
    addon: "KitsuAddon",
    kitsu_project_id: str,
) -> Anatomy:
    print("get_kitsu_project_anatomy")

    kitsu_project_response = await addon.kitsu.get(f"data/projects/{kitsu_project_id}")
    if kitsu_project_response.status_code != 200:
        raise AyonException("Could not get Kitsu project")

    kitsu_project = kitsu_project_response.json()

    resolution_width, resolution_height = [
        int(x) for x in kitsu_project.get("resolution", "1920x1080").split("x")
    ]

    attributes = {
        "description": kitsu_project.get("description", ""),
        "fps": kitsu_project.get("fps", 25),
        "resolutionWidth": resolution_width,
        "resolutionHeight": resolution_height,
        "startDate": kitsu_project.get("start_date") + "T00:00:00Z",
        "endDate": kitsu_project.get("end_date") + "T00:00:00Z",
    }

    statuses = await parse_statuses(addon, kitsu_project_id)
    task_types = await parse_task_types(addon, kitsu_project_id)

    anatomy = Anatomy(
        attributes=attributes,
        task_types=task_types,
        statuses=statuses,
    )

    return anatomy

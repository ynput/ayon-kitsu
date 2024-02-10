from pprint import pprint
from typing import TYPE_CHECKING, Any

import gazu
from nxtools import slugify

from kitsu_common.utils import (
    get_entity_by_kitsu_id,
    parse_attrib,
    create_short_name,
    get_task_type_short_name_by_task_name,
)

if TYPE_CHECKING:
    from ayon_api.entity_hub import EntityHub, FolderEntity


def kitsu_task_new(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    """
        task_type (str): Type of task. Task type must be available in
            config of project folder types.
        entity_id (Union[str, None]): Id of the entity. New id is created if
            not passed.
        parent_id (Union[str, None]): Id of parent entity.
        name (str): Name of entity.
        label (Optional[str]): Folder label.
        attribs (Dict[str, Any]): Attribute values.
        data (Dict[str, Any]): Entity data (custom data).
        thumbnail_id (Union[str, None]): Id of entity's thumbnail.
        active (bool): Is entity active.
        created (Optional[bool]): Entity is new. When 'None' is passed the
            value is defined based on value of 'entity_id'.

    "taskType": kitsu_task["task_type"]["name"],
    "label": kitsu_task["task_type"]["name"],
    "name": kitsu_task["task_type"]["name"],
    "id": kitsu_shot["data"]["ayon_id"],
    "folderId": kitsu_shot["data"]["ayon_id"],
    "data": {"kitsuId": kitsu_task["id"]},
    "ownAttrib": {},
    "active": True,
    """
    kitsu_task: dict[str, Any] = gazu.task.get_task(kitsu_event["task_id"])
    kitsu_shot = gazu.shot.get_shot(kitsu_task["entity_id"])
    task_name = get_task_type_short_name_by_task_name(
        kitsu_task["task_type"]["name"],
        ay_project.project_entity,
    )
    task = ay_project.add_new_task(
        task_type=kitsu_task["task_type"]["name"],
        parent_id=kitsu_shot["data"]["ayon_id"],
        name=task_name,
        data={"kitsuId": kitsu_task["id"]},
    )
    
    

    # Add ayon ID to the task's data in Kitsu so we later can fetch it directly
    if kitsu_task["data"] is None:
        kitsu_task["data"] = {}
    kitsu_task["data"]["ayon_id"] = task.id
    gazu.task.update_task(kitsu_task)
    ay_project.commit_changes()


def kitsu_task_update(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    return
    kitsu_task = gazu.task.get_task(kitsu_event["task_id"])
    ay_task: "FolderEntity" = ay_project.get_task_by_id(kitsu_task["data"]["ayon_id"])
    ay_task.status = kitsu_task["name"]
    # TODO As Kitsu have nb_frames instead of start/end frame we need to calculate the endFrame from nb_frames + startFrame
    for key, value in parse_attrib(kitsu_task).items():
        ay_folder.attribs[key] = value


def kitsu_task_delete(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    return
    ayon_task = get_entity_by_kitsu_id(kitsu_event["task_id"], ay_project)
    if ayon_task:
        ayon_task.parent.remove_child(ayon_task)

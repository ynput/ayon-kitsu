import json
import time

from typing import Any, Literal, get_args, TYPE_CHECKING

from nxtools import logging, log_traceback

from ayon_server.entities import FolderEntity, TaskEntity, ProjectEntity
from ayon_server.lib.postgres import Postgres
from ayon_server.types import OPModel, Field

from .anatomy import parse_attrib
from .utils import (
    get_folder_by_kitsu_id,
    get_task_by_kitsu_id,
    create_folder,
    update_folder,
    create_task,
    update_task
)


if TYPE_CHECKING:
    from .. import KitsuAddon
    from ayon_server.entities import UserEntity


EntityDict = dict[str, Any]

KitsuEntityType = Literal[
    "Asset",
    "Shot",
    "Sequence",
    "Episode",
    "Task",
]


class PushEntitiesRequestModel(OPModel):
    project_name: str
    entities: list[EntityDict] = Field(..., title="List of entities to sync")


async def get_root_folder_id(
    user: "UserEntity",
    project_name: str,
    kitsu_type: KitsuEntityType,
    kitsu_type_id: str,
    subfolder_id: str | None = None,
    subfolder_name: str | None = None,
) -> str:
    """
    Get the root folder ID for a given Kitsu type and ID.
    If a folder/subfolder does not exist, it will be created.
    """
    res = await Postgres.fetch(
        f"""
        SELECT id FROM project_{project_name}.folders
        WHERE data->>'kitsuId' = $1
        """,
        kitsu_type_id,
    )

    if res:
        id = res[0]["id"]
    else:
        folder = await create_folder(
            project_name=project_name,
            name=kitsu_type,
            data={"kitsuId": kitsu_type_id},
        )
        id = folder.id

    if not (subfolder_id or subfolder_name):
        return id

    res = await Postgres.fetch(
        f"""
        SELECT id FROM project_{project_name}.folders
        WHERE data->>'kitsuId' = $1
        """,
        subfolder_id,
    )

    if res:
        sub_id = res[0]["id"]
    else:
        sub_folder = await create_folder(
            project_name=project_name,
            name=subfolder_name,
            parent_id=id,
            data={"kitsuId": subfolder_id},
        )
        sub_id = sub_folder.id
    return sub_id


async def sync_folder(
    addon,
    user,
    project,
    existing_folders,
    entity_dict,
):
    target_folder = await get_folder_by_kitsu_id(
        project.name,
        entity_dict["id"],
        existing_folders,
    )

    if target_folder is None:
        if entity_dict["type"] == "Asset":
            if entity_dict.get("entity_type_id") in existing_folders:
                parent_id = existing_folders[entity_dict["entity_type_id"]]
            else:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project.name,
                    kitsu_type="Assets",
                    kitsu_type_id="asset",
                    subfolder_id=entity_dict["entity_type_id"],
                    subfolder_name=entity_dict["asset_type_name"],
                )
                existing_folders[entity_dict["entity_type_id"]] = parent_id

        elif entity_dict["type"] == "Episode":
            if entity_dict.get("parent_id") is None:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project.name,
                    kitsu_type="Episodes",
                    kitsu_type_id="episode",
                )
            else:
                if entity_dict.get("parent_id") in existing_folders:
                    parent_id = existing_folders[entity_dict["parent_id"]]
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project.name,
                        entity_dict["parent_id"],
                        existing_folders,
                    )
                    parent_id = parent_folder.id

        elif entity_dict["type"] == "Sequence":
            if entity_dict.get("parent_id") is None:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project.name,
                    kitsu_type="Sequences",
                    kitsu_type_id="sequence",
                )
            else:
                if entity_dict.get("parent_id") in existing_folders:
                    parent_id = existing_folders[entity_dict["parent_id"]]
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project.name, entity_dict["parent_id"], existing_folders
                    )
                    parent_id = parent_folder.id

        elif entity_dict["type"] == "Shot":
            if entity_dict.get("parent_id") is None:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project.name,
                    kitsu_type="Shots",
                    kitsu_type_id="shot",
                )
            else:
                if entity_dict.get("parent_id") in existing_folders:
                    parent_id = existing_folders[entity_dict["parent_id"]]
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project.name, entity_dict["parent_id"], existing_folders
                    )
                    parent_id = parent_folder.id

        else:
            return

        logging.info(f"Creating {entity_dict['type']} '{entity_dict['name']}'")
        target_folder = await create_folder(
            project_name=project.name,
            attrib=parse_attrib(entity_dict.get("data", {})),
            name=entity_dict["name"],
            folder_type=entity_dict["type"],
            parent_id=parent_id,
            data={"kitsuId": entity_dict["id"]},
        )
        existing_folders[entity_dict["id"]] = target_folder.id

    else:
        changed = await update_folder(
            project_name=project.name,
            folder_id=target_folder.id,
            attrib=parse_attrib(entity_dict.get("data", {})),
            name=entity_dict["name"],
            folder_type=entity_dict["type"],
        )
        if changed:
            logging.info(f"Updating {entity_dict['type']} '{entity_dict['name']}'")
            existing_folders[entity_dict["id"]] = target_folder.id

async def ensure_task_type(project, task_type_name) -> bool:
    """ #TODO: kitsu listener for new task types would be preferable """
    if task_type_name not in [ task_type["name"] for task_type in project.task_types ]:
        logging.info(
            f"Creating task type {task_type_name} for '{project.name}'"
        )
        project.task_types.append(
            {
                "name": task_type_name,
                "short_name": task_type_name[:4],
            }
        )
        await project.save()
        return True
    return False

async def ensure_task_status(project, task_status_name) -> bool:
    """ #TODO: kitsu listener for new task statuses would be preferable """

    if task_status_name not in [ status["name"] for status in project.statuses ]:
        logging.info(
            f"Creating task status {task_status_name} for '{project.name}'"
        )
        project.statuses.append(
            {
                "name": task_status_name,
                "short_name": task_status_name[:4],
            }
        )
        await project.save()
        return True
    return False

async def sync_task(
    addon,
    user,
    project,
    existing_tasks,
    existing_folders,
    entity_dict,
):    
    if 'task_status_name' in entity_dict:
        await ensure_task_status(project, entity_dict['task_status_name'])

    if 'task_type_name' in entity_dict:
        await ensure_task_type(project, entity_dict['task_type_name'])
    
    target_task = await get_task_by_kitsu_id(
        project.name,
        entity_dict["id"],
        existing_tasks,
    )

    if target_task is None:
        # Sync task
        if entity_dict.get("entity_id") in existing_folders:
            parent_id = existing_folders[entity_dict["entity_id"]]
        else:
            parent_folder = await get_folder_by_kitsu_id(
                project.name, entity_dict["entity_id"], existing_folders
            )

            if parent_folder is None:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project.name,
                    kitsu_type="Edits",
                    kitsu_type_id="edits",
                )
            else:
                parent_id = parent_folder.id

        logging.info(f"Creating {entity_dict['type']} '{entity_dict['name']}'")
        target_task = await create_task(
            project_name=project.name,
            folder_id=parent_id,
            status=entity_dict["task_status_name"],
            task_type=entity_dict["task_type_name"],
            name=entity_dict["name"],
            data={"kitsuId": entity_dict["id"]},
            # TODO: assignees
        )
        existing_tasks[entity_dict["id"]] = target_task.id

    else:
        changed = await update_task(
            project_name=project.name,
            task_id=target_task.id,
            name=entity_dict.get("name", target_task.name),
            status=entity_dict.get("task_status_name", target_task.status),
            task_type=entity_dict.get("task_type_name", target_task.task_type),
        )
        if changed:
            logging.info(f"Updating {entity_dict['type']} '{entity_dict['name']}'")
            existing_tasks[entity_dict["id"]] = target_task.id


async def push_entities(
    addon: "KitsuAddon",
    user: "UserEntity",
    payload: PushEntitiesRequestModel,
) -> list:
    start_time = time.time()
    project = await ProjectEntity.load(payload.project_name)
    
    # A mapping of kitsu entity ids to folder ids
    # they are added when a task or folder is created or updated and returned by the method - useful for testing

    # This object only exists during the request
    # and speeds up the process of finding folders
    # if multiple entities are requested to sync
  
    folders = {}
    tasks = {}

    for entity_dict in payload.entities:
        if entity_dict["type"] not in get_args(KitsuEntityType):
            logging.warning(f"Unsupported kitsu entity type: {entity_dict['type']}")
            continue

        # we need to sync folders first
        if entity_dict["type"] != "Task":
            await sync_folder(
                addon,
                user,
                project,
                folders,
                entity_dict,
            )

        else:
            await sync_task(
                addon,
                user,
                project,
                tasks,
                folders,
                entity_dict,
            )

    logging.info(
        f"Synced {len(payload.entities)} entities in {time.time() - start_time}s"
    )

    # pass back the map of kitsu to ayon ids
    return {'folders': folders, 'tasks': tasks}

async def delete_entities(
    addon: "KitsuAddon",
    user: "UserEntity",
    payload: PushEntitiesRequestModel,
) -> list:
    raise NotImplementedError()
import json
import time

from typing import Any, Literal, get_args, TYPE_CHECKING

from nxtools import logging

from ayon_server.entities import FolderEntity, TaskEntity, ProjectEntity
from ayon_server.lib.postgres import Postgres
from ayon_server.types import OPModel, Field

from .anatomy import parse_attrib
from .utils import (
    get_folder_by_kitsu_id,
    get_task_by_kitsu_id,
    create_folder,
    create_task,
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

        logging.info(f"Creating {entity_dict['type']} {entity_dict['name']}")
        target_folder = await create_folder(
            project_name=project.name,
            attrib=parse_attrib(entity_dict.get("data", {})),
            name=entity_dict["name"],
            folder_type=entity_dict["type"],
            parent_id=parent_id,
            data={"kitsuId": entity_dict["id"]},
        )

    else:
        folder = await FolderEntity.load(project.name, target_folder.id)
        changed = False
        for key, value in parse_attrib(entity_dict.get("data", {})).items():
            if getattr(folder.attrib, key) != value:
                print(
                    key,
                    json.dumps(value),
                    "changed from",
                    json.dumps(getattr(folder.attrib, key)),
                )
                setattr(folder.attrib, key, value)
                if key not in folder.own_attrib:
                    folder.own_attrib.append(key)
                changed = True
        if changed:
            logging.info(f"Updating {entity_dict['type']} {entity_dict['name']}")
            await folder.save()


async def sync_task(
    addon,
    user,
    project,
    existing_tasks,
    existing_folders,
    entity_dict,
):
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

        if entity_dict["task_type_name"] not in [
            task_type["name"] for task_type in project.task_types
        ]:
            logging.info(
                f"Creating task type {entity_dict['task_type_name']} for {project.name}"
            )
            project.task_types.append(
                {
                    "name": entity_dict["task_type_name"],
                    "short_name": entity_dict["task_type_name"][:4],
                }
            )
            await project.save()

        logging.info(f"Creating {entity_dict['type']} {entity_dict['name']}")
        target_task = await create_task(
            project_name=project.name,
            folder_id=parent_id,
            status=entity_dict["task_status_name"],
            task_type=entity_dict["task_type_name"],
            name=entity_dict["name"],
            data={"kitsuId": entity_dict["id"]},
            # TODO: assignees
        )

    else:
        task = await TaskEntity.load(project.name, target_task.id)
        changed = False
        for key, value in parse_attrib(entity_dict.get("data", {})).items():
            if getattr(task.attrib, key) != value:
                setattr(task.attrib, key, value)
                if key not in task.own_attrib:
                    task.own_attrib.append(key)
                changed = True
        if changed:
            logging.info(f"Updating {entity_dict['type']} {entity_dict['name']}")
            await task.save()


async def push_entities(
    addon: "KitsuAddon",
    user: "UserEntity",
    payload: PushEntitiesRequestModel,
) -> None:
    start_time = time.time()
    project = await ProjectEntity.load(payload.project_name)

    # A mapping of kitsu entity ids to folder ids
    # This object only exists during the request
    # and speeds up the process of finding folders
    # if multiple entities are requested to sync
    existing_folders = {}
    existing_tasks = {}

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
                existing_folders,
                entity_dict,
            )

        else:
            await sync_task(
                addon,
                user,
                project,
                existing_tasks,
                existing_folders,
                entity_dict,
            )

    logging.info(
        f"Synced {len(payload.entities)} entities in {time.time() - start_time}s"
    )

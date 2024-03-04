import json
import time
from typing import TYPE_CHECKING, Any, Literal, get_args

import httpx
from nxtools import logging

from ayon_server.auth.session import Session
from ayon_server.entities import (
    FolderEntity,
    ProjectEntity,
    UserEntity,
)
from ayon_server.helpers.deploy_project import anatomy_to_project_data
from ayon_server.lib.postgres import Postgres
from ayon_server.types import Field, OPModel


from .anatomy import get_kitsu_project_anatomy, parse_attrib
from .constants import (
    CONSTANT_KITSU_MODELS,
)
from .model_utils import (
    calculate_end_frame,
    create_access_group,
    create_folder,
    create_task,
    create_user,
    delete_folder,
    delete_task,
    delete_user,
    delete_project,
    get_folder_by_kitsu_id,
    get_task_by_kitsu_id,
    get_user_by_kitsu_id,
    get_project_by_kitsu_id,
    get_root_folder_id,
    generate_user_settings,
    update_folder,
    update_task,
    update_user,
    update_project,
)
from .format_utils import (
    to_username,
)

if TYPE_CHECKING:
    from .. import KitsuAddon


EntityDict = dict[str, Any]

KitsuEntityType = Literal[
    "Asset",
    "Shot",
    "Sequence",
    "Episode",
    "Edit",
    "Concept",
    "Task",
    "Person",
    "Project",
]


class PushEntitiesRequestModel(OPModel):
    project_name: str
    entities: list[EntityDict] = Field(..., title="List of entities to sync")
    mock: bool | None = None  # optional param for tests


class RemoveEntitiesRequestModel(OPModel):
    project_name: str
    entities: list[EntityDict] = Field(..., title="List of entities to remove")


async def sync_person(
    addon: "KitsuAddon",
    user: "UserEntity",
    project: "ProjectEntity",
    existing_users: dict[str, Any],
    entity_dict: "EntityDict",
    settings: Any,
):
    logging.info(f"sync_person: {entity_dict['first_name']} {entity_dict['last_name']}")

    username = to_username(entity_dict["first_name"], entity_dict["last_name"])

    payload = await generate_user_settings(
        entity_dict["role"],
        project.name,
        settings,
    ) | {
        "attrib": {
            "fullName": entity_dict["full_name"],
            "email": entity_dict["email"],
        }
    }
    payload["data"]["kitsuId"] = entity_dict["id"]

    ayon_user = None
    try:
        ayon_user = await UserEntity.load(username)
    except Exception:
        pass
    target_user = await get_user_by_kitsu_id(entity_dict["id"], existing_users)

    # User exists but doesn't have a kitsuId assigned it it
    if ayon_user and not target_user:
        target_user = ayon_user

    if target_user:  # Update user
        await update_user(target_user, username, **payload)

    else:  # Create user
        settings = await addon.get_studio_settings()
        password = settings.sync_settings.sync_users.default_password.strip()
        await create_user(username, password, **payload)

    # update the id map
    existing_users[entity_dict["id"]] = username


async def sync_project(
    addon: "KitsuAddon",
    user: "UserEntity",
    entity_dict: "EntityDict",
    mock: bool = False,
):
    logging.info(f"sync_project {entity_dict['id']}")

    project = await get_project_by_kitsu_id(entity_dict["id"])
    logging.info(f"project {project}")
    if not project:
        return

    await addon.ensure_kitsu(mock)
    anatomy = await get_kitsu_project_anatomy(addon, entity_dict["id"])
    anatomy_data = anatomy_to_project_data(anatomy)

    await update_project(project.name, **anatomy_data)


async def sync_folder(
    addon: "KitsuAddon",
    user: "UserEntity",
    project: "ProjectEntity",
    existing_folders: dict[str, Any],
    entity_dict: "EntityDict",
):
    target_folder = await get_folder_by_kitsu_id(
        project.name,
        entity_dict["id"],
        existing_folders,
    )

    # Add description to attrib data
    data: dict[str, str | int | None] | None = entity_dict.get("data", {})
    # The value of key data might be None, in that case, create a new dict
    if data is None:
        data = {}
    if entity_dict.get("description"):
        data["description"] = entity_dict["description"]

    if target_folder is None:
        parent_folder = None
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
        elif entity_dict["type"] in get_args(KitsuEntityType):
            if entity_dict.get("parent_id") is None:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project.name,
                    kitsu_type=f"{entity_dict['type']}s",
                    kitsu_type_id=entity_dict["type"].lower(),
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
                    if parent_folder is None:
                        logging.warning(
                            f"Parent folder for {entity_dict['type']} {entity_dict['name']} not found. Skipping."  # noqa
                        )
                        return
                    parent_id = parent_folder.id
        else:
            logging.warning("Unsupported entity type: ", entity_dict["type"])
            return
        # ensure folder type exists
        if entity_dict["type"] not in [f["name"] for f in project.folder_types]:
            logging.warning(
                f"Folder type {entity_dict['type']} does not exist. Creating."
            )
            project.folder_types.append(
                {"name": entity_dict["type"]}
                | CONSTANT_KITSU_MODELS.get(entity_dict["type"], {})
            )
            await project.save()

        logging.info(f"Creating {entity_dict['type']} {entity_dict['name']}")
        if not parent_folder:
            parent_folder = await FolderEntity.load(project.name, parent_id)

        # Calculate the end-frame
        frame_out = calculate_end_frame(entity_dict, parent_folder)
        if frame_out:
            data["frame_out"] = frame_out

        target_folder = await create_folder(
            project_name=project.name,
            attrib=parse_attrib(data),
            name=entity_dict["name"],
            folder_type=entity_dict["type"],
            parent_id=parent_id,
            data={"kitsuId": entity_dict["id"]},
        )
        existing_folders[entity_dict["id"]] = target_folder.id

    else:
        # Calculate the end-frame
        frame_out = calculate_end_frame(entity_dict, target_folder)
        if frame_out:
            data["frame_out"] = frame_out

        changed = await update_folder(
            project_name=project.name,
            folder_id=target_folder.id,
            attrib=parse_attrib(data),
            name=entity_dict["name"],
            folder_type=entity_dict["type"],
        )
        if changed:
            logging.info(f"Updating {entity_dict['type']} '{entity_dict['name']}'")
            existing_folders[entity_dict["id"]] = target_folder.id


async def ensure_task_type(
    project: "ProjectEntity",
    task_type_name: str,
) -> bool:
    """#TODO: kitsu listener for new task types would be preferable"""
    if task_type_name not in [task_type["name"] for task_type in project.task_types]:
        logging.info(f"Creating task type {task_type_name} for '{project.name}'")
        project.task_types.append(
            {
                "name": task_type_name,
                "short_name": task_type_name[:4],
            }
        )
        await project.save()
        return True
    return False


async def ensure_task_status(
    project: "ProjectEntity",
    task_status_name: str,
) -> bool:
    """#TODO: kitsu listener for new task statuses would be preferable"""

    if task_status_name not in [status["name"] for status in project.statuses]:
        logging.info(f"Creating task status {task_status_name} for '{project.name}'")
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
    addon: "KitsuAddon",
    user: "UserEntity",
    project: "ProjectEntity",
    existing_tasks: dict[str, Any],
    existing_folders: dict[str, Any],
    entity_dict: "EntityDict",
):
    if "task_status_name" in entity_dict:
        await ensure_task_status(project, entity_dict["task_status_name"])

    if "task_type_name" in entity_dict:
        await ensure_task_type(project, entity_dict["task_type_name"])

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

            if parent_folder:
                parent_id = parent_folder.id
            else:
                # The new task type haven't bin implemented in Ayon yet
                logging.warning(
                    f"The type '{entity_dict['name']}' isn't implemented yet."
                    f"Currently they aren't supported"
                )
                return

        logging.info(f"Creating {entity_dict['type']} '{entity_dict['name']}'")
        target_task = await create_task(
            project_name=project.name,
            folder_id=parent_id,
            status=entity_dict["task_status_name"],
            task_type=entity_dict["task_type_name"],
            name=entity_dict["name"],
            data={"kitsuId": entity_dict["id"]},
            assignees=entity_dict["assignees"],
        )
        existing_tasks[entity_dict["id"]] = target_task.id

    else:
        changed = await update_task(
            project_name=project.name,
            task_id=target_task.id,
            name=entity_dict.get("name", target_task.name),
            assignees=entity_dict.get("assignees", target_task.assignees),
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
) -> dict[str, dict[Any, Any]]:
    start_time = time.time()
    project = None
    if payload.project_name != "":
        project = await ProjectEntity.load(payload.project_name)

    # A mapping of kitsu entity ids to folder ids
    # they are added when a task or folder is created or updated and returned by the method - useful for testing

    # This object only exists during the request
    # and speeds up the process of finding folders
    # if multiple entities are requested to sync

    folders = {}
    tasks = {}
    users = {}

    settings = await addon.get_studio_settings()
    for entity_dict in payload.entities:
        # required fields
        if "type" not in entity_dict:
            logging.error(f"No kitsu entity type found for entity: {entity_dict}")
            continue
        if "id" not in entity_dict:
            logging.error(f"No kitsu id found for entity: {entity_dict}")
            continue

        if entity_dict["type"] not in get_args(KitsuEntityType):
            logging.warning(f"Unsupported kitsu entity type: {entity_dict['type']}")
            continue

        try:
            if entity_dict["type"] == "Project":
                await sync_project(addon, user, entity_dict, payload.mock)
            elif entity_dict["type"] == "Person":
                if settings.sync_settings.sync_users.enabled:
                    await create_access_group(settings)
                    await sync_person(
                        addon,
                        user,
                        project,
                        users,
                        entity_dict,
                        settings,
                    )
            elif entity_dict["type"] != "Task":
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
        except Exception as e:
            logging.error(f"Sync failed for entity {entity_dict} with exception: {e}")

    logging.info(
        f"Synced {len(payload.entities)} entities in {time.time() - start_time}s"
    )

    # pass back the map of kitsu to ayon ids
    return {"folders": folders, "tasks": tasks, "users": users}


async def remove_entities(
    addon: "KitsuAddon",
    user: "UserEntity",
    payload: RemoveEntitiesRequestModel,
) -> dict[str, dict[Any, Any]]:
    start_time = time.time()
    project = await ProjectEntity.load(payload.project_name)

    # A mapping of kitsu entity ids to folder ids
    # they are added when a task or folder are deleted and returned by the method - useful for testing
    folders = {}
    tasks = {}

    settings = await addon.get_studio_settings()
    for entity_dict in payload.entities:
        if entity_dict["type"] not in get_args(KitsuEntityType):
            logging.warning(f"Unsupported kitsu entity type: {entity_dict['type']}")
            continue

        try:
            if entity_dict["type"] == "Project":
                if settings.sync_settings.delete_projects:
                    target_project = await get_project_by_kitsu_id(entity_dict["id"])
                    if not target_project:
                        continue
                    await delete_project(project_name=target_project.name, user=user)

            elif entity_dict["type"] == "Person":
                target_user = await get_user_by_kitsu_id(entity_dict["id"])
                if not target_user:
                    continue

                await delete_user(target_user.name, user=user)

            elif entity_dict["type"] == "Task":
                task = await get_task_by_kitsu_id(
                    project.name,
                    entity_dict["id"],
                    tasks,
                )
                if not task:
                    continue

                await delete_task(
                    project_name=project.name,
                    task_id=task.id,
                    user=user,
                )
                logging.info(f"Deleted {entity_dict['type']} '{task.name}'")
                tasks[entity_dict["id"]] = task.id

            else:
                folder = await get_folder_by_kitsu_id(
                    project.name,
                    entity_dict["id"],
                    folders,
                )
                if not folder:
                    continue

                await delete_folder(
                    project_name=project.name,
                    folder_id=folder.id,
                    user=user,
                )
                logging.info(f"Deleted {entity_dict['type']} '{folder.name}'")
                folders[entity_dict["id"]] = folder.id

        except Exception as e:
            logging.error(f"Remove failed for entity {entity_dict} with exception: {e}")

    logging.info(
        f"Deleted {len(payload.entities)} entities in {time.time() - start_time}s"
    )

    # pass back the map of kitsu to ayon ids
    return {"folders": folders, "tasks": tasks}

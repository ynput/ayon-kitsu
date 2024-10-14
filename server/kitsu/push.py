import json
import time
from typing import TYPE_CHECKING, Any, Literal, get_args

import httpx
from nxtools import logging

from ayon_server.auth.session import Session
from ayon_server.entities import FolderEntity, ProjectEntity, UserEntity
from ayon_server.helpers.deploy_project import anatomy_to_project_data
from ayon_server.lib.postgres import Postgres
from ayon_server.types import Field, OPModel

from .anatomy import get_kitsu_project_anatomy, parse_attrib
from .constants import (
    CONSTANT_KITSU_MODELS,
)
from .utils import (
    calculate_end_frame,
    create_folder,
    create_task,
    delete_folder,
    delete_task,
    delete_project,
    get_folder_by_kitsu_id,
    get_task_by_kitsu_id,
    get_user_by_kitsu_id,
    update_project,
    update_folder,
    update_task,
)


from .addon_helpers import to_username, required_values

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


async def create_access_group(
    addon: "KitsuAddon",
    user: "UserEntity",
    entity_dict: "EntityDict",
    name: str | None = None,
):
    try:
        if not name:
            settings = await addon.get_studio_settings()
            name = settings.sync_settings.sync_users.access_group
        session = await Session.create(user)
        headers = {"Authorization": f"Bearer {session.token}"}
        # Check if group already exists
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{entity_dict['ayon_server_url']}/api/accessGroups/_",
                headers=headers,
            )

        for group in response.json():
            if group["name"] == name:
                # access group already exists
                return

        # Create a new access group
        payload = json.dumps(
            {
                "create": {"enabled": False, "access_list": []},
                "read": {"enabled": False, "access_list": []},
                "update": {"enabled": False, "access_list": []},
                "publish": {"enabled": False, "access_list": []},
                "delete": {"enabled": False, "access_list": []},
                "attrib_read": {"enabled": False, "attributes": []},
                "attrib_write": {"enabled": False, "attributes": []},
                "endpoints": {"enabled": False, "endpoints": []},
            }
        )

        async with httpx.AsyncClient() as client:
            return await client.put(
                f"{entity_dict['ayon_server_url']}/api/accessGroups/{name}/_",
                content=payload,
                headers=headers,
            )
    except Exception as e:
        print(e)


def match_ayon_roles_with_kitsu_role(role: str) -> dict[str, bool]:
    match role:
        case "admin":
            return {
                "isAdmin": True,
                "isManager": False,
            }
        case "manager":
            return {
                "isAdmin": False,
                "isManager": True,
            }
        case "user":
            return {
                "isAdmin": False,
                "isManager": False,
            }
        case _:
            return {}


async def generate_user_settings(
    addon: "KitsuAddon",
    entity_dict: "EntityDict",
):
    settings = await addon.get_studio_settings()
    data: dict[str, Any] = {}
    match entity_dict["role"]:
        case "admin":  # Studio manager
            data = match_ayon_roles_with_kitsu_role(
                settings.sync_settings.sync_users.roles.admin
            )
        case "vendor":  # Vendor
            data = match_ayon_roles_with_kitsu_role(
                settings.sync_settings.sync_users.roles.vendor
            )
        case "client":  # Client
            data = match_ayon_roles_with_kitsu_role(
                settings.sync_settings.sync_users.roles.client
            )
        case "manager":  # Manager
            data = match_ayon_roles_with_kitsu_role(
                settings.sync_settings.sync_users.roles.manager
            )
        case "supervisor":  # Supervisor
            data = match_ayon_roles_with_kitsu_role(
                settings.sync_settings.sync_users.roles.supervisor
            )
        case "user":  # Artist
            data = match_ayon_roles_with_kitsu_role(
                settings.sync_settings.sync_users.roles.user
            )
    return data | {
        "data": {
            "defaultAccessGroups": [settings.sync_settings.sync_users.access_group],
        },
    }


async def sync_person(
    addon: "KitsuAddon",
    user: "UserEntity",
    existing_users: dict[str, Any],
    entity_dict: "EntityDict",
):
    first_name, entity_id = required_values(entity_dict, ["first_name", "id"])
    last_name = entity_dict.get("last_name", "")

    # == check should Person entity be synced ==
    # do not sync Kitsu API bots
    if entity_dict.get("is_bot"):
        logging.info(f"skipping sync_person for Kitsu Bot: {first_name} {last_name}")
        return

    logging.info(f"sync_person: {first_name} {last_name}")
    username = to_username(first_name, last_name)

    payload = {
        "name": username,
        "attrib": {
            "fullName": entity_dict.get("full_name", ""),
            "email": entity_dict.get("email", ""),
        },
    } | await generate_user_settings(
        addon,
        entity_dict,
    )
    payload["data"]["kitsuId"] = entity_id

    ayon_user = None
    try:
        ayon_user = await UserEntity.load(username)
    except Exception:
        pass
    target_user = await get_user_by_kitsu_id(entity_id)

    # User exists but doesn't have a kitsuId assigned it it
    if ayon_user and not target_user:
        target_user = ayon_user

    if target_user:  # Update user
        try:
            session = await Session.create(user)
            headers = {"Authorization": f"Bearer {session.token}"}

            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{entity_dict['ayon_server_url']}/api/users/{target_user.name}",
                    json=payload,
                    headers=headers,
                )
            # Rename the user
            # TODO: We should discourage renaming users.
            # Maybe just change the fullName in the case there's a typo,
            # but changing username may have weird side effects.
            payload = {"newName": username}
            async with httpx.AsyncClient() as client:
                await client.patch(
                    f"{entity_dict['ayon_server_url']}/api/users/{target_user.name}/rename",
                    json=payload,
                    headers=headers,
                )
        except Exception as e:
            print(e)
    else:  # Create user
        user = UserEntity(payload)
        settings = await addon.get_studio_settings()
        user.set_password(settings.sync_settings.sync_users.default_password)
        await user.save()

    # update the id map
    existing_users[entity_id] = username


async def sync_project(
    addon: "KitsuAddon",
    user: "UserEntity",
    project: "ProjectEntity",
    entity_dict: "EntityDict",
    mock: bool = False,
):
    logging.info("sync_project")
    (entity_id,) = required_values(entity_dict, ["id"])

    if not project:
        logging.info("sync project not found")
        return

    # only sync if the project has the correct kitsu id stored on it. will succeed when paired correctly
    if project.data.get("kitsuProjectId") != entity_id:
        logging.info(
            f"project.data.kitsuProjectId {project.data.get('kitsuProjectId')} not matching entity {entity_id}"
        )
        return

    await addon.ensure_kitsu(mock)
    anatomy = await get_kitsu_project_anatomy(addon, entity_id)
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
        data["frame_out"] = calculate_end_frame(entity_dict, parent_folder)

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
        data["frame_out"] = calculate_end_frame(entity_dict, target_folder)

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
        assert "type" in entity_dict
        assert "id" in entity_dict

        if entity_dict["type"] not in get_args(KitsuEntityType):
            logging.warning(f"Unsupported kitsu entity type: {entity_dict['type']}")
            continue

        if entity_dict["type"] == "Project":
            await sync_project(addon, user, project, entity_dict, payload.mock)
        elif entity_dict["type"] == "Person":
            if settings.sync_settings.sync_users.enabled:
                await create_access_group(
                    addon,
                    user,
                    entity_dict,
                )
                await sync_person(
                    addon,
                    user,
                    users,
                    entity_dict,
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

        if entity_dict["type"] == "Project":
            if settings.sync_settings.delete_projects:
                await update_project(
                    addon,
                    user,
                    project,
                    entity_dict,
                )
        elif entity_dict["type"] == "Person":
            target_user = await get_user_by_kitsu_id(entity_dict["id"])
            if not target_user:
                continue

            await target_user.delete()

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

    logging.info(
        f"Deleted {len(payload.entities)} entities in {time.time() - start_time}s"
    )

    # pass back the map of kitsu to ayon ids
    return {"folders": folders, "tasks": tasks}

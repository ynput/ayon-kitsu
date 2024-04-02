import unicodedata
from typing import Any
import re

from nxtools import slugify

from ayon_server.entities import (
    FolderEntity,
    TaskEntity,
    UserEntity,
    ProjectEntity,
)
from ayon_server.access.access_groups import AccessGroups
from ayon_server.access.permissions import Permissions
from ayon_server.events import dispatch_event
from ayon_server.lib.postgres import Postgres
from ayon_server.exceptions import ForbiddenException
from .format_utils import create_name_and_label


async def get_root_folder_id(
    user: "UserEntity",
    project_name: str,
    kitsu_type: str,
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
    settings: Any,
    name: str | None = None,
):
    try:
        if not name:
            name = settings.sync_settings.sync_users.access_group

        scope = "_"

        # get access group by name
        for ag_key, _perms in AccessGroups.access_groups.items():
            access_group_name, pname = ag_key

            # if it already exists go no further
            if pname == scope and access_group_name == name:
                return

        # Create a new access group
        permissions = Permissions.from_record(
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

        return AccessGroups.add_access_group(name, scope, permissions)

    except Exception as e:
        print(e)


async def generate_user_settings(
    role: str,
    project_name: str,
    settings: Any,
):
    data: dict[str, str] = {}
    match role:
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
        case _:  # Artist
            data = match_ayon_roles_with_kitsu_role(
                settings.sync_settings.sync_users.roles.user
            )

    return {
        "data": data
        | {
            "accessGroups": {
                project_name: [settings.sync_settings.sync_users.access_group]
            },
            "defaultAccessGroups": [settings.sync_settings.sync_users.access_group],
        },
    }


def match_ayon_roles_with_kitsu_role(role: str) -> dict[str, bool] | None:
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
        case _:
            return {
                "isAdmin": False,
                "isManager": False,
            }


def calculate_end_frame(
    entity_dict: dict[str, int], folder: FolderEntity
) -> int | None:
    # for concepts data=None
    if "data" not in entity_dict or not isinstance(entity_dict["data"], dict):
        return

    # return end-frame if set
    if entity_dict["data"].get("frame_out"):
        return entity_dict["data"].get("frame_out")

    # Calculate the end-frame
    if entity_dict.get("nb_frames") and not entity_dict["data"].get("frame_out"):
        frame_start = entity_dict["data"].get("frame_in")
        # If kitsu doesn't have a frame in, get it from the folder in Ayon
        if frame_start is None and hasattr(folder.attrib, "frameStart"):
            frame_start = folder.attrib.frameStart
        if frame_start is not None:
            return int(frame_start) + int(entity_dict["nb_frames"])


async def get_project_by_kitsu_id(
    kitsu_id: str,
) -> ProjectEntity | None:
    """Get an Ayon ProjectEntity by its Kitsu ID"""

    res = await Postgres.fetch(
        "SELECT name FROM projects WHERE data->>'kitsuProjectId' = $1",
        kitsu_id,
    )
    if not res:
        return None
    return await ProjectEntity.load(res[0]["name"])


async def get_user_by_kitsu_id(
    kitsu_id: str,
    existing_users: dict[str, str] | None = None,
) -> UserEntity | None:
    """Get an Ayon UserEndtity by its Kitsu ID"""

    if existing_users and (kitsu_id in existing_users):
        user_name = existing_users[kitsu_id]
    else:
        res = await Postgres.fetch(
            "SELECT name FROM public.users WHERE data->>'kitsuId' = $1",
            kitsu_id,
        )
        if not res:
            return None
        user_name = res[0]["name"]

    return await UserEntity.load(user_name)


async def get_folder_by_kitsu_id(
    project_name: str,
    kitsu_id: str,
    existing_folders: dict[str, str] | None = None,
) -> FolderEntity | None:
    """Get an Ayon FolderEndtity by its Kitsu ID"""

    if existing_folders and (kitsu_id in existing_folders):
        folder_id = existing_folders[kitsu_id]

    else:
        res = await Postgres.fetch(
            f"""
            SELECT id FROM project_{project_name}.folders
            WHERE data->>'kitsuId' = $1
            """,
            kitsu_id,
        )
        if not res:
            return None
        folder_id = res[0]["id"]

    return await FolderEntity.load(project_name, folder_id)


async def get_task_by_kitsu_id(
    project_name: str,
    kitsu_id: str,
    existing_tasks: dict[str, str] | None = None,
) -> TaskEntity | None:
    """Get an Ayon TaskEntity by its Kitsu ID"""

    if existing_tasks and (kitsu_id in existing_tasks):
        folder_id = existing_tasks[kitsu_id]

    else:
        res = await Postgres.fetch(
            f"""
            SELECT id FROM project_{project_name}.tasks
            WHERE data->>'kitsuId' = $1
            """,
            kitsu_id,
        )
        if not res:
            return None
        folder_id = res[0]["id"]

    return await TaskEntity.load(project_name, folder_id)


async def create_folder(
    project_name: str,
    name: str,
    **kwargs,
) -> FolderEntity:
    """
    TODO: This is a re-implementation of create folder, which does not
    require background tasks. Maybe just use the similar function from
    api.folders.folders.py?
    """
    payload = {**kwargs, **create_name_and_label(name)}

    folder = FolderEntity(
        project_name=project_name,
        payload=payload,
    )
    await folder.save()
    event = {
        "topic": "entity.folder.created",
        "description": f"Folder {folder.name} created",
        "summary": {"entityId": folder.id, "parentId": folder.parent_id},
        "project": project_name,
    }

    await dispatch_event(**event)
    return folder


async def update_folder(
    project_name: str,
    folder_id: str,
    name: str,
    **kwargs,
) -> bool:
    folder = await FolderEntity.load(project_name, folder_id)
    changed = False

    payload: dict[str, Any] = {**kwargs, **create_name_and_label(name)}

    for key in ["name", "label"]:
        if key in payload and getattr(folder, key) != payload[key]:
            setattr(folder, key, payload[key])
            changed = True

    for key, value in payload["data"].items():
        if folder.data.get(key) != value:
            folder.data[key] = value
            changed = True

    for key, value in payload["attrib"].items():
        if getattr(folder.attrib, key) != value:
            setattr(folder.attrib, key, value)
            if key not in folder.own_attrib:
                folder.own_attrib.append(key)
            changed = True
    if changed:
        await folder.save()
        event = {
            "topic": "entity.folder.updated",
            "description": f"Folder {folder.name} updated",
            "summary": {"entityId": folder.id, "parentId": folder.parent_id},
            "project": project_name,
        }
        await dispatch_event(**event)

    return changed


async def delete_folder(
    project_name: str,
    folder_id: str,
    user: "UserEntity",
    **kwargs,
) -> None:
    folder = await FolderEntity.load(project_name, folder_id)

    # do we need this?
    await folder.ensure_delete_access(user)

    await folder.delete()
    event = {
        "topic": "entity.folder.deleted",
        "description": f"Folder {folder.name} deleted",
        "summary": {"entityId": folder.id, "parentId": folder.parent_id},
        "project": project_name,
    }
    await dispatch_event(**event)


async def create_task(
    project_name: str,
    name: str,
    **kwargs,
) -> TaskEntity:
    payload = {**kwargs, **create_name_and_label(name)}
    task = TaskEntity(
        project_name=project_name,
        payload=payload,
    )

    await task.save()
    event = {
        "topic": "entity.task.created",
        "description": f"Task {task.name} created",
        "summary": {"entityId": task.id, "parentId": task.parent_id},
        "project": project_name,
    }
    await dispatch_event(**event)
    return task


async def update_task(
    project_name: str,
    task_id: str,
    name: str,
    **kwargs,
) -> bool:
    task = await TaskEntity.load(project_name, task_id)
    changed = False

    payload = {**kwargs, **create_name_and_label(name)}

    # keys that can be updated
    for key in ["name", "label", "status", "task_type", "assignees"]:
        if key in payload and getattr(task, key) != payload[key]:
            setattr(task, key, payload[key])
            changed = True
    if "attrib" in payload:
        for key, value in payload["attrib"].items():
            if getattr(task.attrib, key) != value:
                setattr(task.attrib, key, value)
                if key not in task.own_attrib:
                    task.own_attrib.append(key)
                changed = True
    if changed:
        await task.save()
        event = {
            "topic": "entity.task.updated",
            "description": f"Task {task.name} updated",
            "summary": {"entityId": task.id, "parentId": task.parent_id},
            "project": project_name,
        }
        await dispatch_event(**event)
    return changed


async def delete_task(
    project_name: str,
    task_id: str,
    user: "UserEntity",
    **kwargs,
) -> None:
    task = await TaskEntity.load(project_name, task_id)

    # do we need this?
    await task.ensure_delete_access(user)

    await task.delete()
    event = {
        "topic": "entity.task.deleted",
        "description": f"Task {task.name} deleted",
        "summary": {"entityId": task.id, "parentId": task.parent_id},
        "project": project_name,
    }
    await dispatch_event(**event)


async def update_user(
    user: Any,
    name: str,
    **kwargs,
) -> bool:
    changed = False
    payload = kwargs

    # update name
    if user.name != name:
        await Postgres.execute(
            "UPDATE users SET name = $1 WHERE name = $2",
            name,
            user.name,
        )
        changed = True

    # keys that can be updated
    for key in ["data"]:
        if key in payload and getattr(user, key) != payload[key]:
            setattr(user, key, payload[key])
            changed = True
    if "attrib" in payload:
        for key, value in payload["attrib"].items():
            if getattr(user.attrib, key) != value:
                setattr(user.attrib, key, value)
                if key not in user.own_attrib:
                    user.own_attrib.append(key)
                changed = True
    if changed:
        await user.save()
        event = {
            "topic": "entity.user.updated",
            "description": f"User {user.name} updated",
            "summary": {"userName": user.name},
        }
        await dispatch_event(**event)
    return changed


async def create_user(
    name: str,
    password: str | None,
    **kwargs,
):
    user = UserEntity({"name": name, **kwargs})

    if password:
        user.set_password(password)
    await user.save()
    event = {
        "topic": "entity.user.created",
        "description": f"User {user.name} created",
        "summary": {"userName": user.name},
    }
    await dispatch_event(**event)
    return user


async def delete_user(
    name: str,
    user: "UserEntity",
) -> None:
    _user = await UserEntity.load(name)

    # do we need this?
    await user.ensure_delete_access(_user)

    await _user.delete()
    event = {
        "topic": "entity.user.deleted",
        "description": f"User {_user.name} deleted",
        "summary": {"userName": _user.name},
    }
    await dispatch_event(**event)


async def update_project(
    name: str,
    **kwargs,
):
    project = await ProjectEntity.load(name)
    changed = False

    for key, value in kwargs.items():
        if key == "attrib":
            for k, v in value.items():
                if getattr(project.attrib, k) != v:
                    setattr(project.attrib, k, v)
                    if k not in project.own_attrib:
                        project.own_attrib.append(k)
                    changed = True

        elif getattr(project, key) != value:
            setattr(project, key, value)
            changed = True

    if changed:
        await project.save()
        event = {
            "topic": "entity.project.updated",
            "description": f"Project {project.name} updated",
            "summary": {"ProjectName": project.name},
        }
        await dispatch_event(**event)
    return changed


async def delete_project(project_name: str, user: "UserEntity"):
    project = await ProjectEntity.load(project_name)
    if not user.is_manager:
        raise ForbiddenException("You need to be a manager in order to delete projects")
    await project.delete()
    event = {
        "topic": "entity.project.deleted",
        "description": f"Project {project_name} deleted",
        "summary": {"projectName": project_name},
    }
    await dispatch_event(**event)

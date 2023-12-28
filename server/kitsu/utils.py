import re

from typing import Any

from ayon_server.lib.postgres import Postgres
from ayon_server.entities import FolderEntity, TaskEntity
from ayon_server.events import dispatch_event


async def get_folder_by_kitsu_id(
    project_name: str,
    kitsu_id: str,
    existing_folders: dict[str, str] | None = None,
) -> FolderEntity:
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
        existing_folders[kitsu_id] = folder_id

    return await FolderEntity.load(project_name, folder_id)

    return None


async def get_task_by_kitsu_id(
    project_name: str,
    kitsu_id: str,
    existing_tasks: dict[str, str] | None = None,
) -> TaskEntity:
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
        existing_tasks[kitsu_id] = folder_id

    return await TaskEntity.load(project_name, folder_id)

    return None


async def create_folder(
    project_name: str,
    name: str,
    attrib: dict[str, Any] | None = None,
    **kwargs,
) -> FolderEntity:
    """
    TODO: This is a re-implementation of create folder, which does not
    require background tasks. Maybe just use the similar function from
    api.folders.folders.py?
    """
    # ensure name is correctly formatted
    if name:
        name = to_entity_name(name)

    folder = FolderEntity(
        project_name=project_name,
        payload=dict(kwargs, name=name),
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


async def create_task(
    project_name: str,
    name: str,
    attrib: dict[str, Any] | None = None,
    **kwargs,
) -> TaskEntity:

    # ensure name is correctly formatted
    if name:
        name = to_entity_name(name)


    task = TaskEntity(
        project_name=project_name,
        payload=dict(kwargs, name=name),
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


def to_entity_name(kitsu_name) -> str:
    """ convert kitsu names so they will pass Ayon Entity name validation """
    name = kitsu_name.strip()
    # replace whitespace
    name = re.sub(r'\s+', "_", name)
    # remove any invalid characters
    name = re.sub(r'[^a-zA-Z0-9_\.\-]', '', name)
    return name
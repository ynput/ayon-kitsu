from typing import Any

from nxtools import slugify, logging

from ayon_server.entities import (
    ProjectEntity,
    FolderEntity,
    TaskEntity,
    UserEntity,
)
from ayon_server.events import dispatch_event
from ayon_server.lib.postgres import Postgres


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
    if entity_dict.get("nb_frames") and not entity_dict["data"].get(
        "frame_out"
    ):
        frame_start = entity_dict["data"].get("frame_in")
        # If kitsu doesn't have a frame in, get it from the folder in Ayon
        if frame_start is None and hasattr(folder.attrib, "frameStart"):
            frame_start = folder.attrib.frameStart
        if frame_start is not None:
            return int(frame_start) + int(entity_dict["nb_frames"])


def create_name_and_label(kitsu_name: str) -> dict[str, str]:
    """From a name coming from kitsu, create a name and label"""
    name_slug = slugify(kitsu_name, separator="_")
    return {"name": name_slug, "label": kitsu_name}


async def get_user_by_kitsu_id(
    kitsu_id: str,
) -> UserEntity | None:
    """Get an Ayon UserEndtity by its Kitsu ID"""
    res = await Postgres.fetch(
        "SELECT name FROM public.users WHERE data->>'kitsuId' = $1",
        kitsu_id,
    )
    if not res:
        return None
    user = await UserEntity.load(res[0]["name"])
    return user


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


async def update_project(
    name: str,
    **kwargs,
):
    project = await ProjectEntity.load(name)

    return await update_entity(
        project.name,
        project,
        kwargs,
        # currently only 'task_types' and 'statuses' are set by anatomy.py
        #   and are updatable
        # not updated are "folder_types", "link_types", "tags", "config"
        attr_whitelist=["task_types", "statuses"],
    )


async def update_entity(
    project_name, entity, kwargs, attr_whitelist: list[str] | None = None
):
    """Updates the entity for given attribute whitelist.

    Saves changes and dispatches an update event.
    """

    if attr_whitelist is None:
        attr_whitelist = []

    # keys that can be updated
    for key in attr_whitelist:
        if key in kwargs and getattr(entity, key) != kwargs[key]:
            setattr(entity, key, kwargs[key])
            logging.info(f"setattr {key}")
            changed = True
    if "attrib" in kwargs:
        for key, value in kwargs["attrib"].items():
            if getattr(entity.attrib, key) != value:
                setattr(entity.attrib, key, value)
                if key not in entity.own_attrib:
                    entity.own_attrib.append(key)
                logging.info(
                    f"setattr attrib.{key}"
                    f" {getattr(entity.attrib, key)} => {value}"
                )
                changed = True
    if changed:
        await entity.save()

        summary = {}
        if hasattr(entity, "id"):
            summary["id"] = entity.id
        if hasattr(entity, "parent_id"):
            summary["parent_id"] = entity.parent_id
        if hasattr(entity, "name"):
            summary["name"] = entity.name

        event = {
            "topic": f"entity.{entity.entity_type}.updated",
            "description": f"{entity.entity_type} {entity.name} updated",
            "summary": summary,
            "project": project_name,
        }
        logging.info(f"dispatch_event: {event}")
        await dispatch_event(**event)
    return changed

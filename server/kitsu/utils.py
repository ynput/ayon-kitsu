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
    if entity_dict.get("nb_frames") and not entity_dict["data"].get("frame_out"):
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
    return await create_entity(project_name, folder)


async def update_folder(
    project_name: str,
    folder_id: str,
    name: str,
    **kwargs,
) -> bool:
    folder = await FolderEntity.load(project_name, folder_id)
    kwargs: dict[str, Any] = {**kwargs, **create_name_and_label(name)}

    return await update_entity(
        project_name,
        folder,
        kwargs,
        attr_whitelist=["name", "label"],
    )


async def delete_folder(
    project_name: str,
    folder_id: str,
    user: "UserEntity",
    **kwargs,
) -> None:
    folder = await FolderEntity.load(project_name, folder_id)
    await delete_entity(project_name, folder, user)


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
    return await create_entity(project_name, task)


async def update_task(
    project_name: str,
    task_id: str,
    name: str,
    **kwargs,
) -> bool:
    task = await TaskEntity.load(project_name, task_id)
    kwargs = {**kwargs, **create_name_and_label(name)}

    return await update_entity(
        project_name,
        task,
        kwargs,
        attr_whitelist=["name", "label", "status", "task_type", "assignees"],
    )


async def delete_task(
    project_name: str,
    task_id: str,
    user: "UserEntity",
    **kwargs,
) -> None:
    task = await TaskEntity.load(project_name, task_id)
    await delete_entity(project_name, task, user)


async def update_project(
    name: str,
    **kwargs,
):
    project = await ProjectEntity.load(name)

    return await update_entity(
        project.name,
        project,
        kwargs,
        # currently only 'task_types' and 'statuses' are set by anatomy.py and are updatable
        # not updated are "folder_types",  "link_types", "tags", "config"
        attr_whitelist=["task_types", "statuses"],
    )


## ====================================================


async def create_entity(project_name: str, entity):
    """create a new entity and dispatch a create event, returns the entity"""
    await entity.save()

    summary = {}
    if hasattr(entity, "id"):
        summary["id"] = entity.id
    if hasattr(entity, "parent_id"):
        summary["parent_id"] = entity.parent_id
    if hasattr(entity, "name"):
        summary["name"] = entity.name

    event = {
        "topic": f"entity.{entity.entity_type}.created",
        "description": f"{entity.entity_type} {entity.name} created",
        "summary": summary,
        "project": project_name,
    }
    await dispatch_event(**event)
    return entity


async def update_entity(
    project_name, entity, kwargs, attr_whitelist: list[str] | None = None
) -> bool:
    """updates the entity for given attribute whitelist, saves changes and dispatches an update event"""
    changed = False
    if attr_whitelist is None:
        attr_whitelist = []

    # keys that can be updated
    for key in attr_whitelist:
        if key in kwargs and getattr(entity, key) != kwargs[key]:
            setattr(entity, key, kwargs[key])
            logging.debug(f"setattr {key} {getattr(entity, key)} => {kwargs[key]}")
            changed = True
    if "attrib" in kwargs:
        for key, value in kwargs["attrib"].items():
            if getattr(entity.attrib, key) != value:
                setattr(entity.attrib, key, value)
                if key not in entity.own_attrib:
                    entity.own_attrib.append(key)
                logging.debug(
                    f"setattr attrib.{key} {getattr(entity.attrib, key)} => {value}"
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
        logging.debug(f"dispatch_event: {event}")
        await dispatch_event(**event)
    return changed


async def delete_entity(
    project_name: str,
    entity,
    user: "UserEntity",
) -> None:
    """delete the given entity after checking user permission, dispatches a delete event"""

    # check user permission to delete this entity
    if hasattr(entity, "ensure_delete_access") and callable(
        entity.ensure_delete_access
    ):
        await entity.ensure_delete_access(user)

    await entity.delete()

    summary = {}
    if hasattr(entity, "id"):
        summary["id"] = entity.id
    if hasattr(entity, "parent_id"):
        summary["parent_id"] = entity.parent_id
    if hasattr(entity, "name"):
        summary["name"] = entity.name

    event = {
        "topic": f"entity.{entity.entity_type}.deleted",
        "description": f"{entity.entity_type} {entity.name} deleted",
        "summary": summary,
        "project": project_name,
    }
    logging.debug(f"dispatch_event: {event}")
    await dispatch_event(**event)

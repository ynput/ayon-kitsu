from typing import Any

import httpx
import re
from nxtools import slugify, logging

from ayon_server.entities import (
    ProjectEntity,
    FolderEntity,
    TaskEntity,
    UserEntity,
)
from ayon_server.events import dispatch_event
from ayon_server.lib.postgres import Postgres
from ayon_server.types import NAME_REGEX
from ayon_server.auth.session import Session

from .attrib_parsing import end_frame_from_kitsu
from .constants import sync_event, sync_origin_headers

try:
    from ayon_server.api.context import get_request_context
except ImportError:  # older AYON servers have no request context
    get_request_context = None

try:
    from ayon_server.exceptions import NotFoundException
except ImportError:
    NotFoundException = None


def is_not_found_exception(exc: Exception) -> bool:
    """Return True if exception represents an entity not found in AYON."""
    if (
        NotFoundException is not None
        and isinstance(NotFoundException, type)
        and isinstance(exc, NotFoundException)
    ):
        return True
    if getattr(exc, "status_code", None) == 404:
        return True
    exc_name = type(exc).__name__.lower()
    return "notfound" in exc_name


def request_sender() -> str | None:
    """Return the ``X-Sender`` of the current request, if available."""
    if get_request_context is None:
        return None
    try:
        return get_request_context().sender
    except Exception:
        return None


def calculate_end_frame(
    entity_dict: dict[str, Any], folder: FolderEntity
) -> int | None:
    """Calculate the end frame using Kitsu data and folder attributes.

    Delegates frame arithmetic to ``attrib_parsing.end_frame_from_kitsu``,
    passing ``folder.attrib.frameStart`` as fallback start frame (Task 16.1).

    Args:
        entity_dict: Kitsu entity dictionary.
        folder: AYON folder entity whose attributes may supply a fallback.

    Returns:
        The end frame or None if not determinable.
    """
    fallback = (
        folder.attrib.frameStart
        if hasattr(folder, "attrib") and hasattr(folder.attrib, "frameStart")
        else None
    )
    return end_frame_from_kitsu(entity_dict, fallback_frame_start=fallback)


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
    try:
        return await UserEntity.load(res[0]["name"])
    except Exception as exc:
        if is_not_found_exception(exc):
            return None
        raise


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

    try:
        return await FolderEntity.load(project_name, folder_id)
    except Exception as exc:
        if is_not_found_exception(exc):
            return None
        raise


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

    try:
        return await TaskEntity.load(project_name, folder_id)
    except Exception as exc:
        if is_not_found_exception(exc):
            return None
        raise


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

    await dispatch_event(**sync_event(**event))
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
        await dispatch_event(**sync_event(**event))

    return changed


async def delete_folder(
    project_name: str,
    folder_id: str,
    user: "UserEntity",
    **kwargs,
) -> None:
    try:
        folder = await FolderEntity.load(project_name, folder_id)
    except Exception:
        return

    # do we need this?
    await folder.ensure_delete_access(user)

    await folder.delete()
    event = {
        "topic": "entity.folder.deleted",
        "description": f"Folder {folder.name} deleted",
        "summary": {"entityId": folder.id, "parentId": folder.parent_id},
        "project": project_name,
    }
    await dispatch_event(**sync_event(**event))


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
    await dispatch_event(**sync_event(**event))
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
        await dispatch_event(**sync_event(**event))
    return changed


async def delete_task(
    project_name: str,
    task_id: str,
    user: "UserEntity",
    **kwargs,
) -> None:
    try:
        task = await TaskEntity.load(project_name, task_id)
    except Exception as exc:
        if is_not_found_exception(exc):
            return
        raise

    # do we need this?
    await task.ensure_delete_access(user)

    await task.delete()
    event = {
        "topic": "entity.task.deleted",
        "description": f"Task {task.name} deleted",
        "summary": {"entityId": task.id, "parentId": task.parent_id},
        "project": project_name,
    }
    await dispatch_event(**sync_event(**event))


def _ensure_safe_project_name(project_name: str) -> None:
    """Validate project_name to prevent SQL injection in table names."""
    if not re.fullmatch(NAME_REGEX, project_name):
        raise ValueError(f"Invalid project name '{project_name}'")


async def get_link_by_io(
    project_name: str,
    input_id: str,
    output_id: str,
    link_type: str,
) -> str | None:
    """Get a link ID by input/output IDs and link type.

    Query the database for an existing link matching the given input,
    output, and link type. Return the first matching link's ID, or None
    if no link exists.

    Args:
        project_name: AYON project name (validated for SQL safety).
        input_id: AYON folder ID of the link input (source).
        output_id: AYON folder ID of the link output (target).
        link_type: Link type identifier (e.g., "breakdown|folder|folder").

    Returns:
        Link ID string if found, None otherwise.
    """
    _ensure_safe_project_name(project_name)
    res = await Postgres.fetch(
        f"""
        SELECT id FROM project_{project_name}.links
        WHERE input_id = $1 AND output_id = $2 AND link_type = $3
        """,
        input_id,
        output_id,
        link_type,
    )
    if not res:
        return None
    return res[0]["id"]


async def get_links_for_output(
    project_name: str,
    output_id: str,
    link_type: str,
) -> list[dict[str, Any]]:
    """Get all links for a given output folder and link type.

    Query the database for all links where the specified folder is the
    output (target). Return link metadata including ID, input_id, and data.

    Args:
        project_name: AYON project name (validated for SQL safety).
        output_id: AYON folder ID of the link output (target).
        link_type: Link type identifier (e.g., "breakdown|folder|folder").

    Returns:
        List of link dictionaries, each containing:
            - id: Link ID
            - input_id: AYON folder ID of the link input (source)
            - data: Link data dictionary (may contain kitsuAssetId, etc.)
    """
    _ensure_safe_project_name(project_name)
    return await Postgres.fetch(
        f"""
        SELECT id, input_id, data FROM project_{project_name}.links
        WHERE output_id = $1 AND link_type = $2
        """,
        output_id,
        link_type,
    )


async def create_entity_link(
    project_name: str,
    user: "UserEntity",
    ayon_server_url: str,
    input_id: str,
    output_id: str,
    link_type: str,
    data: dict[str, Any] | None = None,
) -> str | None:
    """Create an entity link via AYON REST API.

    Create a link between two folders (input and output) with the specified
    link type. Multiple links with the same input/output/type are allowed
    (e.g., for multi-occurence casting).

    Args:
        project_name: AYON project name.
        user: User entity for authentication.
        ayon_server_url: Base URL of the AYON server.
        input_id: AYON folder ID of the link input (source).
        output_id: AYON folder ID of the link output (target).
        link_type: Link type identifier in format "name|input_type|output_type"
            (e.g., "breakdown|folder|folder").
        data: Optional dictionary containing link metadata (e.g., kitsuAssetId,
            kitsuTargetId,             occurence).

    Returns:
        Created link ID string if successful, None otherwise. Warnings
        on failure.
    """
    session = await Session.create(user)
    headers = sync_origin_headers(session.token, request_sender())
    payload: dict = {
        "input": input_id,
        "output": output_id,
        "linkType": link_type,
    }
    if data:
        payload["data"] = data

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{ayon_server_url}/api/projects/{project_name}/links",
            json=payload,
            headers=headers,
        )
    if res.status_code not in (200, 201):
        logging.warning(
            f"Failed to create link {input_id}->{output_id} "
            f"type '{link_type}': {res.status_code} {res.text}"
        )
        return
    try:
        return res.json().get("id")
    except Exception:
        return None


async def delete_entity_link(
    project_name: str,
    user: "UserEntity",
    ayon_server_url: str,
    link_id: str,
) -> None:
    """Delete an entity link via AYON REST API.

    Delete a link by its ID. Log warnings if the deletion fails.

    Args:
        project_name: AYON project name.
        user: User entity for authentication.
        ayon_server_url: Base URL of the AYON server.
        link_id: ID of the link to delete.

    Returns:
        None. Warnings on failure.
    """
    session = await Session.create(user)
    headers = sync_origin_headers(session.token, request_sender())

    async with httpx.AsyncClient() as client:
        res = await client.delete(
            f"{ayon_server_url}/api/projects/{project_name}/links/{link_id}",
            headers=headers,
        )

    if res.status_code not in (200, 204):
        logging.warning(
            f"Failed to delete link {link_id}: {res.status_code} {res.text}"
        )


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

    changed = False

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

        event = sync_event(
            topic=f"entity.{entity.entity_type}.updated",
            description=f"{entity.entity_type} {entity.name} updated",
            summary=summary,
            project=project_name,
        )
        logging.info(f"dispatch_event: {event}")
        await dispatch_event(**event)
    return changed

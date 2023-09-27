from typing import Any, Literal, get_args, TYPE_CHECKING

from nxtools import logging

from ayon_server.entities import FolderEntity
from ayon_server.events import dispatch_event
from ayon_server.lib.postgres import Postgres
from ayon_server.types import OPModel, Field


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


class SyncEntitiesRequestModel(OPModel):
    project_name: str
    entities: list[EntityDict] = Field(..., title="List of entities to sync")


def parse_attrib(source: dict[str, Any] | None = None):
    result = {}
    if source is None:
        return result
    for key, value in source.items():
        if key == "fps":
            result["fps"] = value
        if key == "frame_in":
            result["frameStart"] = value
        if key == "frame_out":
            result["frameEnd"] = value
        if key == "resolution":
            try:
                result["resolutionWidth"] = int(value.split("x")[0])
                result["resolutionHeight"] = int(value.split("x")[1])
            except (IndexError, ValueError):
                pass
    return result


async def create_folder(
    project_name: str,
    attrib: dict[str, Any] | None = None,
    **kwargs,
) -> FolderEntity:
    """
    TODO: This is a re-implementation of create folder, which does not
    require background tasks. Maybe just use the similar function from
    api.folders.folders.py?
    """
    folder = FolderEntity(
        project_name=project_name,
        payload=kwargs,
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


async def sync_folder(addon, user, project_name, existing_folders, entity_dict):
    target_folder = await get_folder_by_kitsu_id(
        project_name,
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
                    project_name=project_name,
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
                    project_name=project_name,
                    kitsu_type="Episodes",
                    kitsu_type_id="episode",
                )
            else:
                if entity_dict.get("parent_id") in existing_folders:
                    parent_id = existing_folders[entity_dict["parent_id"]]
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project_name,
                        entity_dict["parent_id"],
                    )
                    parent_id = parent_folder.id
                    existing_folders[entity_dict["parent_id"]] = parent_id

        elif entity_dict["type"] == "Sequence":
            if entity_dict.get("parent_id") is None:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project_name,
                    kitsu_type="Sequences",
                    kitsu_type_id="sequence",
                )
            else:
                if entity_dict.get("parent_id") in existing_folders:
                    parent_id = existing_folders[entity_dict["parent_id"]]
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project_name, entity_dict["parent_id"]
                    )
                    parent_id = parent_folder.id
                    existing_folders[entity_dict["parent_id"]] = parent_id

        elif entity_dict["type"] == "Shot":
            if entity_dict.get("parent_id") is None:
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project_name,
                    kitsu_type="Shots",
                    kitsu_type_id="shot",
                )
            else:
                if entity_dict.get("parent_id") in existing_folders:
                    parent_id = existing_folders[entity_dict["parent_id"]]
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project_name, entity_dict["parent_id"]
                    )
                    parent_id = parent_folder.id
                    existing_folders[entity_dict["parent_id"]] = parent_id

        else:
            return

        logging.info(f"Creating {entity_dict['type']} {entity_dict['name']}")
        target_folder = await create_folder(
            project_name=project_name,
            attrib=parse_attrib(entity_dict.get("data", {})),
            name=entity_dict["name"],
            folder_type=entity_dict["type"],
            parent_id=parent_id,
            data={"kitsuId": entity_dict["id"]},
        )

    else:
        logging.info(f"Updating {entity_dict['type']} {entity_dict['name']}")
        folder = await FolderEntity.load(project_name, target_folder.id)
        changed = False
        for key, value in parse_attrib(entity_dict.get("data", {})).items():
            if getattr(folder.attrib, key) != value:
                setattr(folder.attrib, key, value)
                if key not in folder.own_attrib:
                    folder.own_attrib.append(key)
                changed = True
        if changed:
            await folder.save()


async def sync_entities(
    addon: "KitsuAddon",
    user: "UserEntity",
    payload: SyncEntitiesRequestModel,
) -> None:
    project_name = payload.project_name

    # A mapping of kitsu entity ids to folder ids
    # This object only exists during the request
    # and speeds up the process of finding folders
    # if multiple entities are requested to sync
    existing_folders = {}

    for entity_dict in payload.entities:
        assert entity_dict.get("type") in get_args(
            KitsuEntityType
        ), f"Invalid kitsu entity type: {entity_dict.get('type')}"

        if entity_dict["type"] != "Task":
            # Sync folder
            await sync_folder(
                addon,
                user,
                project_name,
                existing_folders,
                entity_dict,
            )

        else:
            # Sync task
            if entity_dict.get("entity_id") in existing_folders:
                parent_id = existing_folders[entity_dict["entity_id"]]
            else:
                parent_folder = await get_folder_by_kitsu_id(
                    project_name, entity_dict["entity_id"]
                )
                parent_id = parent_folder.id
                existing_folders[entity_dict["entity_id"]] = parent_id

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
]


class SyncEntitiesRequestModel(OPModel):
    project_name: str
    entities: list[EntityDict] = Field(..., title="List of entities to sync")


async def create_folder(project_name: str, **kwargs) -> FolderEntity:
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
) -> FolderEntity:
    """
    Get an Ayon FolderEndtity by its Kitsu ID

    TODO: This could be done using a single query.
    Consider rewriting this, if this becomes a bottleneck.
    """
    res = await Postgres.fetch(
        f"""
        SELECT id FROM project_{project_name}.folders
        WHERE data->>'kitsuId' = $1
        """,
        kitsu_id,
    )

    if res:
        return await FolderEntity.load(project_name, res[0]["id"])

    return None


async def sync_entities(
    addon: "KitsuAddon",
    user: "UserEntity",
    payload: SyncEntitiesRequestModel,
) -> None:
    project_name = payload.project_name

    for entity_dict in payload.entities:
        assert entity_dict.get("type") in get_args(
            KitsuEntityType
        ), f"Invalid kitsu entity type: {entity_dict.get('type')}"

        target_folder = await get_folder_by_kitsu_id(project_name, entity_dict["id"])

        if target_folder is None:
            if entity_dict["type"] == "Asset":
                parent_id = await get_root_folder_id(
                    user=user,
                    project_name=project_name,
                    kitsu_type="Assets",
                    kitsu_type_id="asset",
                    subfolder_id=entity_dict["entity_type_id"],
                    subfolder_name=entity_dict["asset_type_name"],
                )

            elif entity_dict["type"] == "Episode":
                if entity_dict.get("parent_id") is None:
                    parent_id = await get_root_folder_id(
                        user=user,
                        project_name=project_name,
                        kitsu_type="Episodes",
                        kitsu_type_id="episode",
                    )
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project_name, entity_dict["parent_id"]
                    )
                    parent_id = parent_folder.id

            elif entity_dict["type"] == "Sequence":
                if entity_dict.get("parent_id") is None:
                    parent_id = await get_root_folder_id(
                        user=user,
                        project_name=project_name,
                        kitsu_type="Sequences",
                        kitsu_type_id="sequence",
                    )
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project_name, entity_dict["parent_id"]
                    )
                    parent_id = parent_folder.id

            elif entity_dict["type"] == "Shot":
                if entity_dict.get("parent_id") is None:
                    parent_id = await get_root_folder_id(
                        user=user,
                        project_name=project_name,
                        kitsu_type="Shots",
                        kitsu_type_id="shot",
                    )
                else:
                    parent_folder = await get_folder_by_kitsu_id(
                        project_name, entity_dict["parent_id"]
                    )
                    parent_id = parent_folder.id
            else:
                continue

            logging.info(
                f"Creating {entity_dict['type']} {entity_dict['name']}"
            )
            target_folder = await create_folder(
                project_name=project_name,
                name=entity_dict["name"],
                folder_type=entity_dict["type"],
                parent_id=parent_id,
                data={"kitsuId": entity_dict["id"]},
            )

from typing import TYPE_CHECKING, Any

import ayon_api
import gazu
from nxtools import logging, slugify

from . import utils

if TYPE_CHECKING:
    from .processor import KitsuProcessor


def _ensure_asset_type_folder(
    project_name: str,
    entity_type_id: str,
    asset_type_name: str,
    folders_by_kitsu_id: dict[str, dict],
) -> str | None:
    """Return the AYON folder id for an asset type, creating it if needed.
    
    Args:
        project_name: The name of the AYON project.
        entity_type_id: The Kitsu entity type id.
        asset_type_name: The name of the asset type.
        folders_by_kitsu_id: A dictionary of AYON folders by Kitsu id.

    Returns:
        The AYON folder id for the asset type, or None if the folder cannot be created.
    """
    asset_type_folder = folders_by_kitsu_id.get(entity_type_id)
    if asset_type_folder:
        return asset_type_folder["id"]

    assets_root = folders_by_kitsu_id.get("asset")
    if not assets_root:
        # Create the Assets folder if it doesn't exist
        assets_root_id = ayon_api.create_folder(
            project_name,
            name="Assets",
            data={"kitsuId": "asset"},
        )
        folders_by_kitsu_id["asset"] = {"id": assets_root_id}
    else:
        assets_root_id = assets_root["id"]

    asset_type_folder_id = ayon_api.create_folder(
        project_name,
        name=slugify(asset_type_name, separator="_"),
        label=asset_type_name,
        parent_id=assets_root_id,
        data={"kitsuId": entity_type_id},
    )
    folders_by_kitsu_id[entity_type_id] = {"id": asset_type_folder_id}
    return asset_type_folder_id


def move_folders_by_asset_type(
    project_name: str, entities: list[dict[str, Any]]
) -> None:
    """Re-parent AYON asset folders when their Kitsu asset type differs.

    Skip moves for folders that already have published products. Leave old
    asset-type folders in place even if they become empty.

    Args:
        project_name: The name of the AYON project.
        entities: List of kitsu entities to process.
    """
    entities_ids: set[str] = {"asset"}
    for entity in entities:
        if entity.get("id"):
            entities_ids.add(entity["id"])
        if entity.get("entity_type_id"):
            entities_ids.add(entity["entity_type_id"])

    folders_by_kitsu_id = utils.get_ayon_folders_by_kitsu_ids(
        project_name, entities_ids
    )

    folders_to_move: list[tuple[dict[str, Any], dict, str]] = []
    for entity in entities:
        entity_type_id = entity["entity_type_id"]
        asset_type_name = entity["asset_type_name"]

        asset_folder = folders_by_kitsu_id.get(entity["id"])

        desired_parent_id = _ensure_asset_type_folder(
            project_name,
            entity_type_id,
            asset_type_name,
            folders_by_kitsu_id,
        )
        if not desired_parent_id:
            logging.warning(
                f"Cannot move asset {entity.get('name')}: "
                "failed to resolve asset type folder"
            )
            continue

        if asset_folder.get("parentId") == desired_parent_id:
            continue

        folders_to_move.append((entity, asset_folder, desired_parent_id))

    if not folders_to_move:
        return

    folder_ids_with_products = {
        product["folderId"]
        for product in ayon_api.get_products(
            project_name,
            folder_ids=[asset_folder["id"] for _, asset_folder, _ in folders_to_move],
            fields={"folderId"},
        )
    }

    for entity, asset_folder, desired_parent_id in folders_to_move:
        if asset_folder["id"] in folder_ids_with_products:
            logging.warning(
                f"Skipping move of asset '{entity.get('name')}' to "
                f"'{entity.get('asset_type_name')}': "
                "folder has published products"
            )
            continue

        logging.info(
            f"Moving asset '{entity.get('name')}' to asset type "
            f"'{entity.get('asset_type_name')}'"
        )
        ayon_api.update_folder(
            project_name,
            asset_folder["id"],
            parent_id=desired_parent_id,
        )


def update_project(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"update_project: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get asset entity
    entity = gazu.project.get_project(data["project_id"])

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_project(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_project: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Add ayon base url so we can use it in REST calls later on
    entity = {}
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_asset(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_asset: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get asset entity
    entity = gazu.asset.get_asset(data["asset_id"])
    entity = utils.preprocess_asset(entity["project_id"], entity)

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    result = ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )
    # Re-parent after push so the folder is guaranteed to exist in AYON
    move_folders_by_asset_type(project_name, [entity])
    return result


def delete_asset(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_asset: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["asset_id"],
        "type": "Asset",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_episode(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_episode: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired
    # Get episode entity
    entity = gazu.shot.get_episode(data["episode_id"])

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_episode(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_episode: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["episode_id"],
        "type": "Episode",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_sequence(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_sequence: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = gazu.shot.get_sequence(data["sequence_id"])

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_sequence(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_sequence: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["sequence_id"],
        "type": "Sequence",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_shot(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_shot: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = gazu.shot.get_shot(data["shot_id"])

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_shot(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_shot: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["shot_id"],
        "type": "Shot",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_task(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_task: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = gazu.task.get_task(data["task_id"])
    entity = utils.preprocess_task(entity["project_id"], entity)

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_task(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_task: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["task_id"],
        "type": "Task",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_edit(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_edit: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get edit entity
    entity = gazu.edit.get_edit(data["edit_id"])

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_edit(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_edit: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["edit_id"],
        "type": "Edit",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_concept(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_concept: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get concept entity
    entity = gazu.concept.get_concept(data["concept_id"])

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_concept(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_concept: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["concept_id"],
        "type": "Concept",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_person(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_person: {data}")
    entity = gazu.person.get_person(data["person_id"])

    # Add ayon base url so we can use it in REST calls later on
    entity["ayon_server_url"] = ayon_api.get_base_url()

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name="",
        entities=[entity],
    )


def delete_person(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_person: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["person_id"],
        "type": "person",
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_casting(
    parent: "KitsuProcessor", data: dict[str, Any]
) -> None:
    """Handle casting update events from Kitsu.

    Process real-time casting update events from Kitsu (shot:casting-update
    or asset:casting-update). Fetch the current casting state from Kitsu,
    create a SyncCasting entity with the complete desired state, and push
    it to AYON for reconciliation.

    NB: currently only supports shot casting updates.
    https://github.com/cgwire/zou/issues/392

    Args:
        parent: KitsuProcessor instance with settings and project pairing info.
        data: Event data dictionary from Kitsu containing:
            - project_id: Kitsu project ID
            One of the following is required:
            - shot_id: Shot ID for shot casting updates
            - asset_id: Asset ID for asset casting updates

    Returns:
        None. The function logs warnings and returns early if:
        - Casting sync is disabled in settings
        - Project is not paired with an AYON project
        - Target entity cannot be determined
        - Casting data cannot be fetched from Kitsu
    """
    logging.info(f"create_or_update_casting received event: {data}")
    sync_casting_settings = (
        parent.settings.get("sync_settings", {})
        .get("sync_casting", {})
    )
    if not sync_casting_settings.get("enabled", False):
        logging.debug("Casting sync is disabled, skipping")
        return
    project_name = parent.get_paired_ayon_project(data.get("project_id"))
    if not project_name:
        logging.debug(f"Project {data.get('project_id')} not paired, skipping")
        return

    # Kitsu sends different fields depending on the event type
    # For shot:casting-update, Kitsu sends shot_id explicitly
    target_id = None
    if data.get("shot_id"):
        target_id = data["shot_id"]
    # For asset:casting-update, Kitsu sends asset_id explicitly
    elif data.get("asset_id"):
        target_id = data["asset_id"]

    if not target_id:
        logging.warning(f"Casting event missing target identifier: {data}")
        return

    try:
        entity = gazu.entity.get_entity(target_id)
        target_type = entity["type"]
        logging.info(
            f"Processing casting update for {target_type} {target_id}"
        )
        if target_type == "Shot":
            casting = gazu.casting.get_shot_casting(entity)
        elif target_type == "Asset":
            casting = gazu.casting.get_asset_casting(entity)
        else:
            logging.warning(
                f"Unable to fetch casting for {target_type.lower()} "
                f"{target_id}: unsupported entity type {entity['type']}"
            )
            return
    except Exception as e:
        logging.warning(
            f"Unable to fetch casting for {target_type.lower()} "
            f"{target_id}: {e}"
        )
        return

    # Extract asset_ids with occurence count
    asset_ids: dict[str, int] = {}
    for actor in casting:
        actor_asset_id = actor.get("asset_id")
        if actor_asset_id:
            asset_ids[actor_asset_id] = asset_ids.get(
                actor_asset_id, 0
            ) + actor.get("nb_occurences", 1)

    # Create SyncCasting entity with complete state
    entity = {
        "id": f"sync-casting-{target_id}",
        "type": "SyncCasting",
        "target_id": target_id,
        "target_type": target_type,
        "asset_ids": asset_ids,
        "project_id": data.get("project_id"),
        "ayon_server_url": ayon_api.get_base_url(),
    }
    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )

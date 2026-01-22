from typing import TYPE_CHECKING

import ayon_api
import gazu
from nxtools import logging

from . import utils

if TYPE_CHECKING:
    from .processor import KitsuProcessor


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

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


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


def create_or_update_casting(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_casting: {data}")
    sync_casting_settings = (
        parent.settings.get("sync_settings", {})
        .get("sync_casting", {})
    )
    if not sync_casting_settings.get("enabled", False):
        return
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return

    # Determine if this is a shot or asset casting update
    shot_id = data.get("shot_id") or data.get("entity_id") or data.get("id")
    asset_id = data.get("asset_id")
    target_type = "Shot"
    target_id = shot_id
    
    if asset_id and not shot_id:
        # This is an asset casting update (asset dependencies)
        target_type = "Asset"
        target_id = asset_id
    elif not shot_id:
        logging.warning("Casting event missing shot_id or asset_id")
        return

    entities: list[dict[str, str]] = []
    
    try:
        if target_type == "Shot":
            casting = gazu.casting.get_shot_casting(target_id)
        else:
            # Asset casting
            asset = gazu.asset.get_asset(target_id)
            casting = gazu.casting.get_asset_casting(asset)
    except Exception as e:
        logging.warning(
            f"Unable to fetch casting for {target_type.lower()} {target_id}: {e}"
        )
        return

    # Extract asset_ids with occurence count
    asset_ids: dict[str, int] = {}
    for item in casting or []:
        if isinstance(item, dict):
            item_asset_id = item.get("asset_id")
            nb_occurences = item.get("nb_occurences", 1)
        else:
            item_asset_id = item
            nb_occurences = 1
        if item_asset_id:
            asset_ids[item_asset_id] = asset_ids.get(item_asset_id, 0) + nb_occurences

    # Create SyncCasting entity with complete state
    entity = {
        "id": f"sync-casting-{target_id}",
        "type": "SyncCasting",
        "target_id": target_id,
        "target_type": target_type,
        "asset_ids": asset_ids,
        "project_id": data["project_id"],
        "ayon_server_url": ayon_api.get_base_url(),
    }
    entities.append(entity)

    if entities:
        return ayon_api.post(
            f"{parent.entrypoint}/push",
            project_name=project_name,
            entities=entities,
        )
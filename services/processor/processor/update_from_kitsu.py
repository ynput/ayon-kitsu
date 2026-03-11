from typing import TYPE_CHECKING, Any

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
            - entity_id: Generic entity ID (type will be detected)

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

    # Determine the target entity (shot or asset whose casting is updated)
    # Kitsu sends different fields depending on the event type
    # Priority: explicit shot_id/asset_id > entity_id (with type detection)
    target_id = None
    target_type = None

    # For shot:casting-update, Kitsu sends shot_id explicitly
    if data.get("shot_id"):
        target_id = data["shot_id"]
        target_type = "Shot"
    # For asset:casting-update, Kitsu sends asset_id explicitly
    elif data.get("asset_id"):
        target_id = data["asset_id"]
        target_type = "Asset"
    # Fallback: entity_id might be present (need to determine type)
    elif data.get("entity_id"):
        target_id = data["entity_id"]
        # Try to determine if it's a shot or asset by attempting to fetch it
        try:
            gazu.shot.get_shot(target_id)
            target_type = "Shot"
        except Exception:
            target_type = "Asset"

    if not target_id:
        logging.warning(f"Casting event missing target identifier: {data}")
        return

    logging.info(f"Processing casting update for {target_type} {target_id}")

    entities: list[dict[str, Any]] = []

    try:
        if target_type == "Shot":
            shot = gazu.shot.get_shot(target_id)
            casting = gazu.casting.get_shot_casting(shot)
        else:
            # Asset casting
            asset = gazu.asset.get_asset(target_id)
            casting = gazu.casting.get_asset_casting(asset)
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
    entities.append(entity)

    if entities:
        return ayon_api.post(
            f"{parent.entrypoint}/push",
            project_name=project_name,
            entities=entities,
        )

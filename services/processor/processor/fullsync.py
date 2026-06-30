import time
from typing import TYPE_CHECKING, Any

import ayon_api
import gazu
from nxtools import logging

if TYPE_CHECKING:
    from .processor import KitsuProcessor

from .utils import (
    get_asset_types,
    get_statuses,
    get_task_types,
    preprocess_asset,
    preprocess_task,
)


def get_assets(
    kitsu_project_id: str, asset_types: dict[str, str]
) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    for record in gazu.asset.all_assets_for_project(kitsu_project_id):
        assets.append(preprocess_asset(kitsu_project_id, record, asset_types))
    return assets


def get_tasks(
    kitsu_project_id: str,
    task_types: dict[str, str],
    task_statuses: dict[str, str]
) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    for record in gazu.task.all_tasks_for_project(kitsu_project_id):
        record["persons"]: list[dict[str, str]] = []
        for id in record["assignees"]:
            record["persons"].append({
                "email": gazu.person.get_person(id)["email"]
            })
        tasks.append(
            preprocess_task(
                kitsu_project_id, record, task_types, task_statuses
            )
        )
    return tasks


def get_casting_links(
    shots: list[dict[str, Any]],
    assets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Get casting links for shots and assets.

    Fetche casting data from Kitsu for all shots and assets, group them by
    target entity, and create SyncCasting entities. Each SyncCasting entity
    contains the complete desired state (asset_ids with occurence counts) for
    full reconciliation, including deletion of stale links.

    Args:
        shots: List of shot dictionaries from gazu API, each containing at
            least
            an "id" field.
        assets: List of asset dictionaries from gazu API, each containing at
            least an "id" field.

    Returns:
        List of SyncCasting entity dictionaries. Each entity contains:
            - id: Unique identifier (format: "sync-casting-{target_id}")
            - type: "SyncCasting"
            - target_id: Kitsu ID of the shot or asset
            - target_type: "Shot" or "Asset"
            - asset_ids: Dictionary mapping asset Kitsu IDs to occurence counts
    """
    casting_entities: list[dict[str, Any]] = []

    # Get casting for shots (which assets are in each shot)
    for shot in shots:
        shot_id = shot.get("id")
        if not shot_id:
            continue
        try:
            casting = gazu.casting.get_shot_casting(shot)
        except Exception as e:
            logging.debug(f"Unable to fetch casting for shot {shot_id}: {e}")
            continue

        # Extract asset_ids with occurence count
        asset_ids: dict[str, int] = {}
        for item in casting or []:
            if isinstance(item, dict):
                asset_id = item.get("asset_id")
                nb_occurences = item.get("nb_occurences", 1)
            else:
                asset_id = item
                nb_occurences = 1
            if asset_id:
                asset_ids[asset_id] = (
                    asset_ids.get(asset_id, 0) + nb_occurences
                )

        # Create SyncCasting entity for this shot
        casting_entities.append({
            "id": f"sync-casting-{shot_id}",
            "type": "SyncCasting",
            "target_id": shot_id,
            "target_type": "Shot",
            "asset_ids": asset_ids,
        })

    # Get casting for assets (asset dependencies / nested assets)
    for asset in assets:
        asset_id = asset.get("id")
        if not asset_id:
            continue
        try:
            casting = gazu.casting.get_asset_casting(asset)
        except Exception as e:
            logging.debug(f"Unable to fetch casting for asset {asset_id}: {e}")
            continue

        # Extract asset_ids with occurence count
        asset_ids: dict[str, int] = {}
        for item in casting or []:
            if isinstance(item, dict):
                linked_asset_id = item.get("asset_id")
                nb_occurences = item.get("nb_occurences", 1)
            else:
                linked_asset_id = item
                nb_occurences = 1
            if linked_asset_id:
                asset_ids[linked_asset_id] = (
                    asset_ids.get(linked_asset_id, 0) + nb_occurences
                )

        # Create SyncCasting entity for this asset
        casting_entities.append({
            "id": f"sync-casting-{asset_id}",
            "type": "SyncCasting",
            "target_id": asset_id,
            "target_type": "Asset",
            "asset_ids": asset_ids,
        })

    logging.debug(f"Found {len(casting_entities)} SyncCasting entities")
    return casting_entities


# Generous timeout for the bulk /push request. The server processes the whole
# entity batch in a single request which can take over the ayon_api default
# of 10s for a full sync. Too short a timeout makes the client stop and retry,
# causing the server to reprocess the entire batch repeatedly.
PUSH_TIMEOUT = 600


def push_entities(
    parent: "KitsuProcessor",
    project_name: str,
    entities: list[dict[str, Any]],
):
    """POST entities to the addon /push endpoint.

    Uses a long timeout and disables retries: the push is a large,
    non-idempotent bulk operation, so re-sending it on a slow
    connection would make the server reprocess every entity again.

    Args:
        parent: The parent processor
        project_name: The Ayon project name
        entities: The list of entities to push
    """
    con = ayon_api.get_server_api_connection()
    prev_max_retries = con.max_retries
    con.set_max_retries(1)
    try:
        return con.raw_post(
            f"{parent.entrypoint}/push",
            json={"project_name": project_name, "entities": entities},
            timeout=PUSH_TIMEOUT,
        )
    finally:
        con.set_max_retries(prev_max_retries)


def project_full_sync(
    parent: "KitsuProcessor", kitsu_project_id: str, project_name: str
):
    """Sync all entities from a Kitsu project to an Ayon project.

    Args:
        parent (KitsuProcessor): The parent processor
        kitsu_project_id (str): The Kitsu project id
        project_name (str): The Ayon
    """
    start_time = time.time()
    logging.info(f"Syncing kitsu project {kitsu_project_id} to {project_name}")
    asset_types = get_asset_types(kitsu_project_id)
    task_statuses = get_statuses()
    task_types = get_task_types(kitsu_project_id)
    persons = gazu.person.all_persons()

    assets = get_assets(kitsu_project_id, asset_types)
    tasks = get_tasks(kitsu_project_id, task_types, task_statuses)
    sync_casting_settings = (
        parent.settings.get("sync_settings", {})
        .get("sync_casting", {})
    )
    casting_enabled = sync_casting_settings.get("enabled", False)

    episodes = gazu.shot.all_episodes_for_project(kitsu_project_id)
    seqs = gazu.shot.all_sequences_for_project(kitsu_project_id)
    shots = gazu.shot.all_shots_for_project(kitsu_project_id)
    edits = gazu.edit.all_edits_for_project(kitsu_project_id)
    # Concepts were introduced at Kitsu/Zou v0.18.0.
    # If the user runs an older version if Kitsu, gazu.concept will
    #    throw an error.
    try:
        concepts = gazu.concept.all_concepts_for_project(kitsu_project_id)
    except Exception:
        concepts = []

    entities = (
        persons + assets + episodes + seqs + shots + edits + concepts + tasks
    )
    if casting_enabled:
        entities += get_casting_links(shots, assets)

    for entity in entities:
        entity["ayon_server_url"] = ayon_api.get_base_url()

    push_entities(parent, project_name, entities)
    logging.info(
        f"Full Sync for project {project_name}"
        f" completed in {time.time() - start_time}s"
    )

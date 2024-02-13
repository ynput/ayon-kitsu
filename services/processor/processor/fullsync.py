import time
from typing import TYPE_CHECKING

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
    kitsu_project_id: str, task_types: dict[str, str], task_statuses: dict[str, str]
) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    for record in gazu.task.all_tasks_for_project(kitsu_project_id):
        record["persons"]: list[dict[str, str]] = []
        for id in record["assignees"]:
            record["persons"].append({"email": gazu.person.get_person(id)["email"]})
        tasks.append(
            preprocess_task(kitsu_project_id, record, task_types, task_statuses)
        )
    return tasks


def full_sync(parent: "KitsuProcessor", kitsu_project_id: str, project_name: str):
    start_time = time.time()
    logging.info(f"Syncing kitsu project {kitsu_project_id} to {project_name}")

    asset_types = get_asset_types(kitsu_project_id)
    task_types = get_task_types(kitsu_project_id)
    task_statuses: dict[str, str] = get_statuses()

    assets = get_assets(kitsu_project_id, asset_types)
    tasks = get_tasks(kitsu_project_id, task_types, task_statuses)

    episodes = gazu.shot.all_episodes_for_project(kitsu_project_id)
    seqs = gazu.shot.all_sequences_for_project(kitsu_project_id)
    shots = gazu.shot.all_shots_for_project(kitsu_project_id)
    edits = gazu.edit.all_edits_for_project(kitsu_project_id)
    concepts = gazu.concept.all_concepts_for_project(kitsu_project_id)

    entities = assets + episodes + seqs + shots + edits + concepts + tasks

    ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=entities,
    )
    logging.info(
        f"Full Sync for project {project_name} completed in {time.time() - start_time}s"
    )

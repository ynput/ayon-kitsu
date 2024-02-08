from typing import TYPE_CHECKING

import ayon_api
import gazu
from nxtools import logging

if TYPE_CHECKING:
    from .processor import KitsuProcessor

from .utils import (
    get_asset_types, get_task_types, get_statuses, 
    preprocess_asset, preprocess_task
)

def get_assets(kitsu_project_id: str, asset_types: {}) -> []:
    assets = []
    for record in gazu.asset.all_assets_for_project(kitsu_project_id):
        assets.append(
            preprocess_asset(kitsu_project_id, record, asset_types)
        )
    return assets

def get_tasks(kitsu_project_id: str, task_types: {}, task_statuses: {}) -> []:
    tasks = []
    for record in gazu.task.all_tasks_for_project(kitsu_project_id):
        tasks.append(
            preprocess_task(kitsu_project_id, record, task_types, task_statuses)
        )
    return tasks


def full_sync(parent: "KitsuProcessor", kitsu_project_id: str, project_name: str):
    logging.info(f"Syncing kitsu project {kitsu_project_id} to {project_name}")

    asset_types = get_asset_types(kitsu_project_id)
    task_types = get_task_types(kitsu_project_id)
    task_statuses = get_statuses()

    assets = get_assets(kitsu_project_id, asset_types)
    tasks = get_tasks(kitsu_project_id, task_types, task_statuses)

    episodes = gazu.shot.all_episodes_for_project(kitsu_project_id)
    seqs = gazu.shot.all_sequences_for_project(kitsu_project_id)
    shots = gazu.shot.all_shots_for_project(kitsu_project_id)
       
    # compile list of entities
    # TODO: split folders and tasks if the list is huge

    entities = assets + episodes + seqs + shots + tasks

    ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=entities,
    )

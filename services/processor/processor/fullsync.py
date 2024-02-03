from pprint import pprint
from typing import TYPE_CHECKING

import ayon_api
import gazu
from nxtools import logging

if TYPE_CHECKING:
    from .kitsu import KitsuProcessor


def get_asset_types(kitsu_project_id: str):
    raw_asset_types = gazu.asset.all_asset_types_for_project(kitsu_project_id)
    kitsu_asset_types = {}
    for asset_type in raw_asset_types:
        kitsu_asset_types[asset_type["id"]] = asset_type["name"]
    return kitsu_asset_types


def get_task_types(kitsu_project_id: str):
    raw_task_types = gazu.task.all_task_types_for_project(kitsu_project_id)
    kitsu_task_types = {}
    for task_type in raw_task_types:
        kitsu_task_types[task_type["id"]] = task_type["name"]
    return kitsu_task_types


def get_statuses():
    raw_statuses = gazu.task.all_task_statuses()
    kitsu_statuses = {}
    for status in raw_statuses:
        kitsu_statuses[status["id"]] = status["name"]
    return kitsu_statuses


def full_sync(parent: "KitsuProcessor", kitsu_project_id: str, project_name: str):
    logging.info(f"Syncing kitsu project {kitsu_project_id} to {project_name}")

    asset_types = get_asset_types(kitsu_project_id)
    task_types = get_task_types(kitsu_project_id)
    task_statuses = get_statuses()

    episodes = gazu.shot.all_episodes_for_project(kitsu_project_id)
    seqs = gazu.shot.all_sequences_for_project(kitsu_project_id)
    shots = gazu.shot.all_shots_for_project(kitsu_project_id)

    #
    # Postprocess data
    #

    assets = []
    for record in gazu.asset.all_assets_for_project(kitsu_project_id):
        asset = {
            **record,
            "asset_type_name": asset_types[record["entity_type_id"]],
        }
        assets.append(asset)

    tasks = []
    for record in gazu.task.all_tasks_for_project(kitsu_project_id):
        task = {
            **record,
            "task_type_name": task_types[record["task_type_id"]],
            "task_status_name": task_statuses[record["task_status_id"]],
        }
        if record["name"] == "main":
            task["name"] = task["task_type_name"].lower()
        tasks.append(task)

        # TODO: replace user uuids in task.assigness with emails
        # which can be used to pair with ayon users

    # compile list of entities
    # TODO: split folders and tasks if the list is huge

    entities = assets + episodes + seqs + shots + tasks

    ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=entities,
    )

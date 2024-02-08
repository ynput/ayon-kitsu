import asyncio
import json
import time
import traceback
from typing import TYPE_CHECKING

import gazu
import ayon_api
from nxtools import logging
# from .sync_server import KitsuInitializer



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


def full_update(*args):
    kitsu_project_id = args[0]['project_id']
    project_name = gazu.project.get_project(kitsu_project_id)['name']
    try:
        ayon_api.delete_project(project_name)
    except:
        pass
    full_sync(args)

def full_delete(*args):
    kitsu_project_id = args[0]['project_id']
    project_name = gazu.project.get_project(kitsu_project_id)['name']
    try:
        ayon_api.delete_project(project_name)
    except:
        pass
    full_sync(args)


def full_sync(*args, **kwargs):
    if kwargs:
        kitsu_project_id = kwargs['project_id']
    elif args:
        try:
            kitsu_project_id = args[0]['project_id']
        except:
            kitsu_project_id = args[0][0]['project_id']

    project_name = gazu.project.get_project(kitsu_project_id)['name']

    addon_name = ayon_api.get_service_addon_name()
    addon_version = ayon_api.get_service_addon_version()
    entrypoint = f"/addons/{addon_name}/{addon_version}"

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

    payload_data = {
        "project_id": kitsu_project_id,
        "project_name": project_name,
        "project_code": project_name.replace(" ", "_"),
    }

    # Convert the dictionary to a JSON string
    payload_json = json.dumps(payload_data)

    # Construct the query string
    payload_query = f'request={payload_json}'

    ayon_api.post(
        f'{entrypoint}/pair?{payload_query}',
        kitsuProjectId = kitsu_project_id,
        ayonProjectName = project_name,
        ayonProjectCode = project_name.replace(' ','_')
    )

    ayon_api.post(
        f"{entrypoint}/push",
        project_name=project_name,
        entities=entities,
    )

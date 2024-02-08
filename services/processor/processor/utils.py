""" utils shared between fullsync.py and update_from_kitsu.py """
from typing import TYPE_CHECKING

import ayon_api
import gazu

from nxtools import logging
from pprint import pprint

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


def preprocess_asset(kitsu_project_id: str, asset: {}, asset_types={}) -> {}:
    if not asset_types:
        asset_types = get_asset_types(kitsu_project_id)
    
    if "entity_type_id" in asset and asset["entity_type_id"] in asset_types:
        asset["asset_type_name"] = asset_types[asset["entity_type_id"]]
    return asset

def preprocess_task(kitsu_project_id: str, task: {}, task_types={}, statuses={}) -> {}:
    if not task_types:
        task_types = get_task_types(kitsu_project_id)

    if not statuses:
        statuses = get_statuses()

    if "task_type_id" in task and task["task_type_id"] in task_types:
        task["task_type_name"] = task_types[task["task_type_id"]]

    if "task_status_id" in task and task["task_status_id"] in statuses:
        task["task_status_name"] = statuses[task["task_status_id"]]

    if 'name' in task and 'task_type_name' in task and task["name"] == "main":
            task["name"] = task["task_type_name"].lower()
    
    # TODO: replace user uuids in task.assigness with emails
    # which can be used to pair with ayon users
    
    return task

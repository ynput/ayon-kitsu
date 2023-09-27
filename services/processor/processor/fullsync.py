from typing import TYPE_CHECKING

import ayon_api
import gazu

from nxtools import logging
from pprint import pprint

if TYPE_CHECKING:
    from .kitsu import KitsuProcessor


def full_sync(parent: "KitsuProcessor", kitsu_project_id: str, project_name: str):
    logging.info(f"Syncing kitsu project {kitsu_project_id} to {project_name}")

    raw_asset_types = gazu.asset.all_asset_types_for_project(kitsu_project_id)

    raw_assets = gazu.asset.all_assets_for_project(kitsu_project_id)
    raw_episodes = gazu.shot.all_episodes_for_project(kitsu_project_id)
    raw_seqs = gazu.shot.all_sequences_for_project(kitsu_project_id)
    raw_shots = gazu.shot.all_shots_for_project(kitsu_project_id)
    raw_tasks = gazu.task.all_tasks_for_project(kitsu_project_id)

    #
    # Postprocess data
    #

    # add asset_type_name to assets
    kitsu_asset_types = {}
    for asset_type in raw_asset_types:
        kitsu_asset_types[asset_type["id"]] = asset_type["name"]

    assets = [
        {**asset, "asset_type_name": kitsu_asset_types[asset["entity_type_id"]]}
        for asset in raw_assets
    ]

    #
    # Tasks
    #

    # TODO: replace user uuids in task.assigness with emails
    # which can be used to pair with ayon users

    # compile list of entities

    # TODO: split folders and tasks if the list is huge

    entities = assets + raw_episodes + raw_seqs + raw_shots  # + raw_tasks

    # for e in entities:
    #     if e["name"] == "sh0010":
    #         print(e)
    #         print()

    ayon_api.post(
        f"{parent.entrypoint}/sync",
        project_name=project_name,
        entities=entities,
    )

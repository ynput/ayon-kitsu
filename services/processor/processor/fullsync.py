from typing import TYPE_CHECKING

import ayon_api
import gazu

from nxtools import logging

if TYPE_CHECKING:
    from .kitsu import KitsuProcessor


def full_sync(parent: "KitsuProcessor", kitsu_project_id: str, project_name: str):
    logging.info(f"Syncing kitsu project {kitsu_project_id} to {project_name}")

    raw_asset_types = gazu.asset.all_asset_types_for_project(kitsu_project_id)

    raw_assets = gazu.asset.all_assets_for_project(kitsu_project_id)
    raw_episodes = gazu.shot.all_episodes_for_project(kitsu_project_id)
    raw_seqs = gazu.shot.all_sequences_for_project(kitsu_project_id)
    raw_shots = gazu.shot.all_shots_for_project(kitsu_project_id)

    kitsu_asset_types = {}
    for asset_type in raw_asset_types:
        kitsu_asset_types[asset_type["id"]] = asset_type["name"]

    assets = [
        {**asset, "asset_type_name": kitsu_asset_types[asset["entity_type_id"]]}
        for asset in raw_assets
    ]

    entities = assets + raw_episodes + raw_seqs + raw_shots

    #
    # Ensure ayon root structure exists and retrieve list of targets
    #

    # entrypoint = f"/addons/{parent.addon_name}/{parent.addon_version}"
    # endpoint = f"{entrypoint}/targets/{project_name}"
    #
    # payload = {
    #     "assetTypes": {i["id"]: i["name"] for i in all_asset_types},
    #     "hasEpisodes": bool(all_episodes),
    #     "hasSequences": bool(all_seqs),
    # }
    #
    # response = ayon_api.post(endpoint, **payload)
    # response.raise_for_status()

    # print(response.data)

    print("***************")

    for e in entities:
        print(e)
        print()


    entrypoint = f"/addons/{parent.addon_name}/{parent.addon_version}/sync"
    ayon_api.post(
        entrypoint,
        project_name=project_name,
        entities=entities,
    )

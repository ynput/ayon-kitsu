""" tests for endpoint 'api/addons/kitsu/{version}/push' 

    $ poetry run pytest tests/test_push.py
"""

import ayon_api
import gazu

from processor import fullsync

from .fixtures import (
    api, 
    kitsu_url, 
    PROJECT_ID, PROJECT_NAME, PROJECT_CODE, 
    PAIR_PROJECT_NAME, PAIR_PROJECT_CODE
)
from . import mock_data

def test_push_assets(api, kitsu_url, monkeypatch):

    # mock the assets
    monkeypatch.setattr(
        gazu.asset, 
        'all_assets_for_project', 
        lambda x: mock_data.all_assets_for_project
    )

    # get the assets merged with asset_types
    entities = fullsync.get_assets(PROJECT_ID,  {
        'asset-type-id-1': 'Character', 
        'asset-type-id-2': 'Rig', 
        'asset-type-id-3': 'Location'
    })
    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")
   
    folders = res.data['hierarchy']
    assert len(folders) == 1
    asset_folder = folders[0]
    assert asset_folder['name'] == "Assets"
    assert asset_folder['label'] == "Assets"
    assert asset_folder['status'] == "Unknown"
    assert asset_folder['hasTasks'] == False
    assert asset_folder['folderType'] == "Folder"
    assert len(asset_folder['children']) == 2
    
    character_folder = asset_folder['children'][0]
    assert character_folder['name'] == "Character"
    assert character_folder['label'] == "Character"
    assert character_folder['folderType'] == "Folder"
    assert character_folder['status'] == "Unknown"
    assert character_folder['hasTasks'] == False
    assert len(character_folder['children']) == 1

    character_1_folder = character_folder['children'][0]
    assert character_1_folder['name'] == "Main_Character"
    assert character_1_folder['label'] == "Main_Character"
    assert character_1_folder['folderType'] == "Asset"
    assert character_1_folder['status'] == "Unknown"
    assert character_1_folder['hasTasks'] == False
    assert not character_1_folder['children']

    rig_folder = asset_folder['children'][1]
    assert rig_folder['name'] == "Rig"
    assert rig_folder['label'] == "Rig"
    assert rig_folder['folderType'] == "Folder"
    assert rig_folder['status'] == "Unknown"
    assert rig_folder['hasTasks'] == False
    assert len(rig_folder['children']) == 1

    character_2_folder = rig_folder['children'][0]
    assert character_2_folder['name'] == "Second_Character"
    assert character_2_folder['label'] == "Second_Character"
    assert character_2_folder['folderType'] == "Asset"
    assert character_2_folder['status'] == "Unknown"
    assert character_2_folder['hasTasks'] == False
    assert not character_2_folder['children']

    
def test_push_episodes(api, kitsu_url):
    # mock episodes
    entities = mock_data.all_episodes_for_project

    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    folders = res.data['hierarchy']
    assert len(folders) == 1

    print(folders)
    episodes_folder = folders[0]
    assert episodes_folder['name'] == "Episodes"
    assert episodes_folder['label'] == "Episodes"
    assert episodes_folder['status'] == "Unknown"
    assert episodes_folder['hasTasks'] == False
    assert episodes_folder['folderType'] == "Folder"
    assert len(episodes_folder['children']) == 2

    ep_1_folder = episodes_folder['children'][0]
    assert ep_1_folder['name'] == "Episode_01"
    assert ep_1_folder['label'] == "Episode_01"
    assert ep_1_folder['folderType'] == "Episode"
    assert ep_1_folder['status'] == "Unknown"
    assert ep_1_folder['hasTasks'] == False
    assert not ep_1_folder['children']

    ep_2_folder = episodes_folder['children'][1]
    assert ep_2_folder['name'] == "Episode_02"
    assert ep_2_folder['label'] == "Episode_02"
    assert ep_2_folder['folderType'] == "Episode"
    assert ep_2_folder['status'] == "Unknown"
    assert ep_2_folder['hasTasks'] == False
    assert not ep_2_folder['children']












""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    where all entities are being created for the first time

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
    assert asset_folder['hasTasks'] is False
    assert asset_folder['folderType'] == "Folder"
    assert len(asset_folder['children']) == 2
    
    character_folder = asset_folder['children'][0]
    assert character_folder['name'] == "Character"
    assert character_folder['label'] == "Character"
    assert character_folder['folderType'] == "Folder"
    assert character_folder['status'] == "Unknown"
    assert character_folder['hasTasks'] is False
    assert len(character_folder['children']) == 1

    character_1_asset = character_folder['children'][0]
    assert character_1_asset['name'] == "Main_Character"
    assert character_1_asset['label'] == "Main_Character"
    assert character_1_asset['folderType'] == "Asset"
    assert character_1_asset['status'] == "Unknown"
    assert character_1_asset['hasTasks'] is False
    assert not character_1_asset['children']

    rig_folder = asset_folder['children'][1]
    assert rig_folder['name'] == "Rig"
    assert rig_folder['label'] == "Rig"
    assert rig_folder['folderType'] == "Folder"
    assert rig_folder['status'] == "Unknown"
    assert rig_folder['hasTasks'] is False
    assert len(rig_folder['children']) == 1

    character_2_asset = rig_folder['children'][0]
    assert character_2_asset['name'] == "Second_Character"
    assert character_2_asset['label'] == "Second_Character"
    assert character_2_asset['folderType'] == "Asset"
    assert character_2_asset['status'] == "Unknown"
    assert character_2_asset['hasTasks'] is False
    assert not character_2_asset['children']

    
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
    assert len(folders) == 2

    episodes_folder = folders[1]
    assert episodes_folder['name'] == "Episodes"
    assert episodes_folder['label'] == "Episodes"
    assert episodes_folder['status'] == "Unknown"
    assert episodes_folder['hasTasks'] is False
    assert episodes_folder['folderType'] == "Folder"
    assert len(episodes_folder['children']) == 2

    ep_1 = episodes_folder['children'][0]
    assert ep_1['name'] == "Episode_01"
    assert ep_1['label'] == "Episode_01"
    assert ep_1['folderType'] == "Episode"
    assert ep_1['status'] == "Unknown"
    assert ep_1['hasTasks'] is False
    assert not ep_1['children']

    ep_2 = episodes_folder['children'][1]
    assert ep_2['name'] == "Episode_02"
    assert ep_2['label'] == "Episode_02"
    assert ep_2['folderType'] == "Episode"
    assert ep_2['status'] == "Unknown"
    assert ep_2['hasTasks'] is False
    assert not ep_2['children']

def test_push_sequences(api, kitsu_url):
     # mock episodes
    entities = mock_data.all_sequences_for_project

    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    folders = res.data['hierarchy']
    assert len(folders) == 2

    episodes_folder = folders[1]
    episode_2 = episodes_folder['children'][1]
    assert len(episode_2['children']) == 2
    assert len(episode_2['children']) == 2

    seq_1 = episode_2['children'][0]
    assert seq_1['name'] == "SEQ01"
    assert seq_1['label'] == "SEQ01"
    assert seq_1['folderType'] == "Sequence"
    assert seq_1['status'] == "Unknown"
    assert seq_1['hasTasks'] is False
    assert not seq_1['children']

    seq_2 = episode_2['children'][1]
    assert seq_2['name'] == "SEQ02"
    assert seq_2['label'] == "SEQ02"
    assert seq_2['folderType'] == "Sequence"
    assert seq_2['status'] == "Unknown"
    assert seq_2['hasTasks'] is False
    assert not seq_2['children']

def test_push_shots(api, kitsu_url):
     # mock shots
    entities = mock_data.all_shots_for_project

    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    folders = res.data['hierarchy']
    assert len(folders) == 2

    episodes_folder = folders[1]
    episode_2 = episodes_folder['children'][1]
    assert len(episode_2['children']) == 2
    assert len(episode_2['children']) == 2

    seq_1 = episode_2['children'][0]
    assert len(seq_1['children']) == 2

    shot_1 = seq_1['children'][0]
    assert shot_1['name'] == "SH001"
    assert shot_1['label'] == "SH001"
    assert shot_1['folderType'] == "Shot"
    assert shot_1['status'] == "Unknown"
    assert shot_1['hasTasks'] is False
    assert not shot_1['children']

    shot_2 = seq_1['children'][1]
    assert shot_2['name'] == "SH002"
    assert shot_2['label'] == "SH002"
    assert shot_2['folderType'] == "Shot"
    assert shot_2['status'] == "Unknown"
    assert shot_2['hasTasks'] is False
    assert not shot_2['children']

    seq_2 = episode_2['children'][1]
    assert len(seq_2['children']) == 1

    shot_3 = seq_2['children'][0]
    assert shot_3['name'] == "SH003"
    assert shot_3['label'] == "SH003"
    assert shot_3['folderType'] == "Shot"
    assert shot_3['status'] == "Unknown"
    assert shot_3['hasTasks'] is False
    assert not shot_3['children']









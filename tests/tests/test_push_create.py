""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    where all entities are being created for the first time

    $ poetry run pytest tests/test_push_create.py
"""

from pprint import pprint

import gazu
from processor import fullsync

from . import mock_data
from .fixtures import (
    PAIR_PROJECT_CODE,
    PAIR_PROJECT_NAME,
    PROJECT_CODE,
    PROJECT_ID,
    PROJECT_NAME,
    api,
    kitsu_url,
)


def test_push_assets(api, kitsu_url, monkeypatch):
    # mock assets
    entities = mock_data.all_assets_for_project_preprocessed

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    folders = res.data["hierarchy"]
    assert len(folders) == 1
    asset_folder = folders[0]
    assert asset_folder["name"] == "assets"
    assert asset_folder["label"] == "Assets"
    assert asset_folder["status"] == "Todo"
    assert asset_folder["hasTasks"] is False
    assert asset_folder["folderType"] == "Folder"
    assert len(asset_folder["children"]) == 2

    character_folder = asset_folder["children"][0]
    assert character_folder["name"] == "character"
    assert character_folder["label"] == "Character"
    assert character_folder["folderType"] == "Folder"
    assert character_folder["status"] == "Todo"
    assert character_folder["hasTasks"] is False
    assert len(character_folder["children"]) == 1

    character_1_asset = character_folder["children"][0]
    assert character_1_asset["name"] == "main_character"
    assert character_1_asset["label"] == "Main Character"
    assert character_1_asset["folderType"] == "Asset"
    assert character_1_asset["status"] == "Todo"
    assert character_1_asset["hasTasks"] is False
    assert not character_1_asset["children"]

    rig_folder = asset_folder["children"][1]
    assert rig_folder["name"] == "rig"
    assert rig_folder["label"] == "Rig"
    assert rig_folder["folderType"] == "Folder"
    assert rig_folder["status"] == "Todo"
    assert rig_folder["hasTasks"] is False
    assert len(rig_folder["children"]) == 1

    character_2_asset = rig_folder["children"][0]
    assert character_2_asset["name"] == "second_character"
    assert character_2_asset["label"] == "Second Character"
    assert character_2_asset["folderType"] == "Asset"
    assert character_2_asset["status"] == "Todo"
    assert character_2_asset["hasTasks"] is False
    assert not character_2_asset["children"]

    # get the full folder data
    res = api.get(f"/projects/{PROJECT_NAME}/folders/{character_2_asset['id']}")
    assert res.status_code == 200
    folder = res.data

    # check the kitsu id is saved to data
    assert folder["data"] == {"kitsuId": "asset-id-2"}


def test_push_episodes(api, kitsu_url):
    # mock episodes
    entities = mock_data.all_episodes_for_project

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    folders = res.data["hierarchy"]
    assert len(folders) == 2

    episodes_folder = folders[1]
    assert episodes_folder["name"] == "episodes"
    assert episodes_folder["label"] == "Episodes"
    assert episodes_folder["status"] == "Todo"
    assert episodes_folder["hasTasks"] is False
    assert episodes_folder["folderType"] == "Folder"
    assert len(episodes_folder["children"]) == 2

    ep_1 = episodes_folder["children"][0]
    assert ep_1["name"] == "episode_01"
    assert ep_1["label"] == "Episode 01"
    assert ep_1["folderType"] == "Episode"
    assert ep_1["status"] == "Todo"
    assert ep_1["hasTasks"] is False
    assert ep_1["parents"] == ["episodes"]
    assert not ep_1["children"]

    ep_2 = episodes_folder["children"][1]
    assert ep_2["name"] == "episode_02"
    assert ep_2["label"] == "Episode 02"
    assert ep_2["folderType"] == "Episode"
    assert ep_2["status"] == "Todo"
    assert ep_2["hasTasks"] is False
    assert ep_2["parents"] == ["episodes"]
    assert not ep_2["children"]


def test_push_sequences(api, kitsu_url):
    # mock episodes
    entities = mock_data.all_sequences_for_project

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    folders = res.data["hierarchy"]
    assert len(folders) == 2

    episodes_folder = folders[1]
    episode_2 = episodes_folder["children"][1]
    assert len(episode_2["children"]) == 2
    assert len(episode_2["children"]) == 2

    seq_1 = episode_2["children"][0]
    assert seq_1["name"] == "seq01"
    assert seq_1["label"] == "SEQ01"
    assert seq_1["folderType"] == "Sequence"
    assert seq_1["status"] == "Todo"
    assert seq_1["hasTasks"] is False
    assert seq_1["parents"] == ["episodes", "episode_02"]
    assert not seq_1["children"]

    seq_2 = episode_2["children"][1]
    assert seq_2["name"] == "seq02"
    assert seq_2["label"] == "SEQ02"
    assert seq_2["folderType"] == "Sequence"
    assert seq_2["status"] == "Todo"
    assert seq_2["hasTasks"] is False
    assert seq_2["parents"] == ["episodes", "episode_02"]
    assert not seq_2["children"]


def test_push_shots(api, kitsu_url):
    # mock shots
    entities = mock_data.all_shots_for_project

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    # lets check what folder structure was saved
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    print(res.data)

    folders = res.data["hierarchy"]
    assert len(folders) == 2

    episodes_folder = folders[1]
    episode_2 = episodes_folder["children"][1]
    assert len(episode_2["children"]) == 2
    assert len(episode_2["children"]) == 2

    seq_1 = episode_2["children"][0]
    assert len(seq_1["children"]) == 2

    shot_1 = seq_1["children"][0]

    assert shot_1["name"] == "sh001"
    assert shot_1["label"] == "SH001"
    assert shot_1["folderType"] == "Shot"
    assert shot_1["status"] == "Todo"
    assert shot_1["parents"] == ["episodes", "episode_02", "seq01"]
    assert shot_1["hasTasks"] is False
    assert not shot_1["children"]

    ## get the full folder details including attributes
    shot_folder_1 = api.get_folder_by_id(PROJECT_NAME, shot_1["id"])
    assert shot_folder_1["attrib"]["fps"] == 25
    assert shot_folder_1["attrib"]["frameStart"] == 0
    assert shot_folder_1["attrib"]["frameEnd"] == 100

    shot_2 = seq_1["children"][1]
    assert shot_2["name"] == "sh002"
    assert shot_2["label"] == "SH002"
    assert shot_2["folderType"] == "Shot"
    assert shot_2["status"] == "Todo"
    assert shot_2["parents"] == ["episodes", "episode_02", "seq01"]
    assert shot_2["hasTasks"] is False
    assert not shot_2["children"]

    ## get the full folder details including attributes
    shot_folder_2 = api.get_folder_by_id(PROJECT_NAME, shot_2["id"])
    assert shot_folder_2["attrib"]["fps"] == 25
    assert shot_folder_2["attrib"]["frameStart"] == 1
    assert shot_folder_2["attrib"]["frameEnd"] == 150
    assert shot_folder_2["path"] == "/episodes/episode_02/seq01/sh002"

    seq_2 = episode_2["children"][1]
    assert len(seq_2["children"]) == 1

    shot_3 = seq_2["children"][0]
    assert shot_3["name"] == "sh003"
    assert shot_3["label"] == "SH003"
    assert shot_3["folderType"] == "Shot"
    assert shot_3["status"] == "Todo"
    assert shot_3["hasTasks"] is False
    assert not shot_3["children"]

    ## get the full folder details including attributes
    shot_folder_3 = api.get_folder_by_id(PROJECT_NAME, shot_3["id"])
    assert shot_folder_3["attrib"]["fps"] == 29.97
    assert shot_folder_3["attrib"]["frameStart"] == 0
    assert shot_folder_3["attrib"]["frameEnd"] == 50
    assert shot_folder_3["path"] == "/episodes/episode_02/seq02/sh003"


def test_push_tasks(api, kitsu_url, monkeypatch):
    entities = mock_data.all_tasks_for_project_preprocessed

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    pprint(res.data)

    """
     res.data should have the created task ids eg. 
    {'folders': {},'tasks': {
        'task-id-1': '0a942808c5e911ee9d540242ac150004',
        'task-id-2': '0a95fb56c5e911ee9d540242ac150004'
    }}
    """
    assert res.data["tasks"], "created task ids should be returned"
    tasks = res.data["tasks"]

    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{tasks['task-id-1']}")
    assert res.status_code == 200
    task_1 = res.data

    assert task_1["taskType"] == "Animation"
    assert task_1["name"] == "animation"
    assert task_1["active"] is True
    assert task_1["assignees"] == ["testkitsu.user1", "testkitsu.user3"]
    assert task_1["label"] == "animation"
    assert task_1["data"] == {"kitsuId": "task-id-1"}
    assert task_1["status"] == "Todo"
    assert task_1["attrib"] == {
        "resolutionHeight": 1080,
        "resolutionWidth": 1920,
        "fps": 25.0,
        "frameStart": 0,
        "frameEnd": 100,
        "handleEnd": 0,
        "handleStart": 0,
        "clipOut": 1,
        "clipIn": 1,
        "pixelAspect": 1.0,
    }

    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{tasks['task-id-2']}")
    assert res.status_code == 200
    task_2 = res.data

    assert task_2["taskType"] == "Compositing"
    assert task_2["name"] == "compositing"
    assert task_2["data"] == {"kitsuId": "task-id-2"}
    assert task_2["status"] == "Approved"  # status not working yet?

    assert task_2["attrib"] == {
        "resolutionHeight": 1080,
        "resolutionWidth": 1920,
        "fps": 25.0,
        "frameStart": 0,
        "frameEnd": 100,
        "handleEnd": 0,
        "handleStart": 0,
        "clipOut": 1,
        "clipIn": 1,
        "pixelAspect": 1.0,
    }

    # ---------------------------------------------
    # lets check what folder hierarchy now has tasks
    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")

    folders = res.data["hierarchy"]
    assert len(folders) == 2

    # shot_1  now has tasks
    episodes_folder = folders[1]
    episode_2 = episodes_folder["children"][1]
    seq_1 = episode_2["children"][0]
    shot_1 = seq_1["children"][0]
    assert shot_1["hasTasks"] is True
    assert shot_1["taskNames"] == ["animation", "compositing"]

    shot_2 = seq_1["children"][1]
    assert shot_2["hasTasks"] is False

    seq_2 = episode_2["children"][1]
    shot_3 = seq_2["children"][0]
    assert shot_3["hasTasks"] is False

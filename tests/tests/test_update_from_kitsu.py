from pprint import pprint

from processor import update_from_kitsu

from . import mock_data
from .fixtures import (
    PROJECT_ID,
    PROJECT_NAME,
    api,
    gazu,
    init_data,
    kitsu_url,
    processor,
)

""" tests for services/processor/update_from_kitsu.py

    $ poetry run pytest tests/test_update_from_kitsu.py 
"""


def test_new_asset(init_data, api, gazu, processor, monkeypatch):
    new_asset = {
        **mock_data.all_assets_for_project[0],
        "id": "new-asset-id-1",
        "name": "My New Asset Name",
    }
    monkeypatch.setattr(gazu.asset, "get_asset", lambda x: new_asset)
    monkeypatch.setattr(
        gazu.asset,
        "all_asset_types_for_project",
        lambda x: mock_data.all_asset_types_for_project,
    )
    monkeypatch.setattr(gazu.project, "get_project", lambda x: mock_data.projects[0])

    data = {
        "asset_id": new_asset["id"],
        "asset_type": "asset-type-id-1",
        "project_id": "project-id-1",
    }
    res = update_from_kitsu.create_or_update_asset(processor, data)

    assert res.status_code == 200
    assert "new-asset-id-1" in res.data["folders"]

    # check the Ayon folder created
    folder_id = res.data["folders"]["new-asset-id-1"]
    folder = api.get_folder_by_id(PROJECT_NAME, folder_id)

    assert folder["label"] == "My New Asset Name"
    assert folder["path"] == "/assets/character/my_new_asset_name"
    assert folder["data"] == {"kitsuId": "new-asset-id-1", "kitsuType": "Asset"}
    assert folder["folderType"] == "Asset"


def test_update_asset(api, gazu, processor, monkeypatch):
    updated_asset = {
        **mock_data.all_assets_for_project[0],
        "name": "My Updated Asset Name",
    }
    monkeypatch.setattr(gazu.asset, "get_asset", lambda x: updated_asset)
    monkeypatch.setattr(
        gazu.asset,
        "all_asset_types_for_project",
        lambda x: mock_data.all_asset_types_for_project,
    )

    data = {
        "asset_id": updated_asset["id"],
        "asset_type": "asset-type-id-1",
        "project_id": "project-id-1",
    }
    res = update_from_kitsu.create_or_update_asset(processor, data)
    assert res.status_code == 200
    assert "asset-id-1" in res.data["folders"]

    # check the Ayon folder created
    folder_id = res.data["folders"]["asset-id-1"]
    folder = api.get_folder_by_id(PROJECT_NAME, folder_id)

    assert folder["label"] == "My Updated Asset Name"
    assert folder["path"] == "/assets/character/my_updated_asset_name"
    assert folder["data"] == {"kitsuId": "asset-id-1", "kitsuType": "Asset"}
    assert folder["folderType"] == "Asset"


def test_delete_asset(api, gazu, processor, monkeypatch):
    asset = mock_data.all_assets_for_project[1]
    monkeypatch.setattr(gazu.asset, "get_asset", lambda x: asset)
    data = {
        "asset_id": asset["id"],
        "asset_type": "asset-type-id-1",
        "project_id": "project-id-1",
    }
    res = update_from_kitsu.delete_asset(processor, data)
    assert res.status_code == 200
    assert asset["id"] in res.data["folders"]


def test_new_task(api, gazu, processor, monkeypatch):
    # add a new Animation task to SH002
    new_task = {
        **mock_data.all_tasks_for_project[0],
        "id": "new-task-id-1",
        "entity_id": "shot-id-2",
        "task_type_id": "task-type-id-1",
        "task_status_id": "task-status-id-1",
    }
    monkeypatch.setattr(gazu.task, "get_task", lambda x: new_task)
    monkeypatch.setattr(
        gazu.task,
        "all_task_types",
        lambda: mock_data.all_task_types,
    )
    monkeypatch.setattr(
        gazu.task, "all_task_statuses", lambda: mock_data.all_task_statuses
    )
    data = {"task_id": new_task["id"], "project_id": "project-id-1"}
    res = update_from_kitsu.create_or_update_task(processor, data)
    assert res.status_code == 200
    assert "new-task-id-1" in res.data["tasks"]

    # check the Ayon task created
    task_id = res.data["tasks"]["new-task-id-1"]

    # note: ayon_api.get_task(project_name, task_id) does not include the status, not sure why
    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{task_id}")
    assert res.status_code == 200
    task = res.data

    assert task["taskType"] == "Animation"
    assert task["status"] == "Todo"

    shot = api.get_folder_by_id(PROJECT_NAME, task["folderId"])

    assert shot["label"] == "SH002"
    assert shot["path"] == "/episodes/episode_02/seq01/sh002"


def test_update_task(api, gazu, processor, monkeypatch):
    # confirm the existing status
    tasks = list(api.get_tasks(PROJECT_NAME))
    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{tasks[1]['id']}")
    task = res.data
    assert task["data"] == {"kitsuId": "task-id-2"}
    assert task["status"] == "Approved"

    # update status  Approved => Todo
    updated_task = {
        **mock_data.all_tasks_for_project[1],
        "id": "task-id-2",
        "task_status_id": "task-status-id-1",
    }

    monkeypatch.setattr(gazu.task, "get_task", lambda x: updated_task)
    monkeypatch.setattr(
        gazu.task,
        "all_task_types",
        lambda: mock_data.all_task_types,
    )
    monkeypatch.setattr(
        gazu.task, "all_task_statuses", lambda: mock_data.all_task_statuses
    )

    data = {"task_id": updated_task["id"], "project_id": "project-id-1"}
    res = update_from_kitsu.create_or_update_task(processor, data)
    assert res.status_code == 200
    assert "task-id-2" in res.data["tasks"]

    # check the Ayon task created
    task_id = res.data["tasks"]["task-id-2"]

    # note: ayon_api.get_task(project_name, task_id) does not include the status, not sure why
    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{task_id}")
    assert res.status_code == 200
    task = res.data

    assert task["taskType"] == "Compositing"
    assert task["status"] == "Todo"

    shot = api.get_folder_by_id(PROJECT_NAME, task["folderId"])

    assert shot["label"] == "SH001"
    assert shot["path"] == "/episodes/episode_02/seq01/sh001"


def test_delete_task(api, gazu, processor, monkeypatch):
    task = mock_data.all_tasks_for_project[1]

    data = {"task_id": task["id"], "project_id": "project-id-1"}
    res = update_from_kitsu.delete_task(processor, data)
    assert res.status_code == 200
    pprint(res.data)
    assert task["id"] in res.data["tasks"]

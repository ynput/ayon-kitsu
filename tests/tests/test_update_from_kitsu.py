from pprint import pprint

import ayon_api
import pytest
from processor import update_from_kitsu

from . import mock_data
from .fixtures import (
    PROJECT_ID,
    PROJECT_NAME,
    access_group,
    api,
    gazu,
    init_data,
    kitsu_url,
    processor,
    users_enabled,
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
    assert folder["data"] == {"kitsuId": "new-asset-id-1"}
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
    assert folder["data"] == {"kitsuId": "asset-id-1"}
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
        "all_task_types_for_project",
        lambda x: mock_data.all_task_types_for_project,
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
        "all_task_types_for_project",
        lambda x: mock_data.all_task_types_for_project,
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


def test_create_or_update_person_new(
    api, gazu, kitsu_url, processor, monkeypatch, users_enabled, access_group
):
    """A brand new Kitsu person (unknown kitsu_id/email) should be pushed."""
    new_person = {
        **mock_data.all_persons[0],
        "id": "person-id-new-1",
        "email": "new.person@temp.com",
        "first_name": "New",
        "last_name": "Person",
        "full_name": "New Person",
    }
    api.delete("/users/new.person")
    monkeypatch.setattr(gazu.person, "get_person", lambda x: new_person)

    data = {"person_id": new_person["id"]}
    res = update_from_kitsu.create_or_update_person(processor, data)

    assert res is not None
    assert res.status_code == 200

    user = api.get_user("new.person")
    assert user["data"]["kitsuId"] == "person-id-new-1"
    assert user["attrib"]["fullName"] == "New Person"

    api.delete("/users/new.person")


def test_create_or_update_person_skips_when_unchanged(
    api, gazu, kitsu_url, processor, monkeypatch, mocker, users_enabled, access_group
):
    """A person whose AYON data already matches Kitsu should not push."""
    person = {
        **mock_data.all_persons[0],
        "id": "person-id-unchanged-1",
        "email": "unchanged.person@temp.com",
        "first_name": "Unchanged",
        "last_name": "Person",
        "full_name": "Unchanged Person",
        "active": True,
    }
    api.delete("/users/unchanged.person")
    monkeypatch.setattr(gazu.person, "get_person", lambda x: person)

    data = {"person_id": person["id"]}
    # first call creates the user in AYON
    res = update_from_kitsu.create_or_update_person(processor, data)
    assert res.status_code == 200

    # second call with identical data should be skipped (no push)
    post_mock = mocker.patch.object(ayon_api, "post")
    res = update_from_kitsu.create_or_update_person(processor, data)
    assert res is None
    post_mock.assert_not_called()

    api.delete("/users/unchanged.person")


def test_create_or_update_person_pushes_when_full_name_changes(
    api, gazu, kitsu_url, processor, monkeypatch, users_enabled, access_group
):
    """Changing full_name in Kitsu should update AYON without renaming
    the user's username."""
    person = {
        **mock_data.all_persons[0],
        "id": "person-id-changed-1",
        "email": "changed.person@temp.com",
        "first_name": "Changed",
        "last_name": "Person",
        "full_name": "Changed Person",
    }
    api.delete("/users/changed.person")
    monkeypatch.setattr(gazu.person, "get_person", lambda x: person)

    data = {"person_id": person["id"]}
    res = update_from_kitsu.create_or_update_person(processor, data)
    assert res.status_code == 200

    updated_person = {**person, "full_name": "Changed Person Renamed"}
    monkeypatch.setattr(gazu.person, "get_person", lambda x: updated_person)
    res = update_from_kitsu.create_or_update_person(processor, data)
    assert res is not None
    assert res.status_code == 200

    user = api.get_user("changed.person")
    assert user["attrib"]["fullName"] == "Changed Person Renamed"
    assert user["name"] == "changed.person"  # username must not change

    api.delete("/users/changed.person")


def test_delete_person_sends_expected_payload(processor, mocker):
    """delete_person must call /remove with an empty project_name and a
    'Person' typed entity — it must not require a paired project."""
    post_mock = mocker.patch.object(ayon_api, "post")

    data = {"person_id": "person-id-payload-1"}
    update_from_kitsu.delete_person(processor, data)

    post_mock.assert_called_once()
    args, kwargs = post_mock.call_args
    assert args[0] == f"{processor.entrypoint}/remove"
    assert kwargs["project_name"] == ""
    assert kwargs["entities"] == [
        {
            "id": "person-id-payload-1",
            "type": "Person",
            "ayon_server_url": ayon_api.get_base_url(),
        }
    ]


def test_delete_person_removes_user_without_paired_project(
    api, gazu, kitsu_url, processor, monkeypatch, users_enabled, access_group
):
    """delete_person should remove the AYON user even when the Kitsu
    project is not paired with any AYON project."""
    person = {
        **mock_data.all_persons[0],
        "id": "person-id-delete-1",
        "email": "delete.person@temp.com",
        "first_name": "Delete",
        "last_name": "Person",
        "full_name": "Delete Person",
    }
    api.delete("/users/delete.person")
    monkeypatch.setattr(gazu.person, "get_person", lambda x: person)

    data = {"person_id": person["id"]}
    res = update_from_kitsu.create_or_update_person(processor, data)
    assert res.status_code == 200
    api.get_user("delete.person")  # should not raise

    class UnpairedProcessor:
        entrypoint = processor.entrypoint

        def get_paired_ayon_project(self, kitsu_project_id):
            return None

    res = update_from_kitsu.delete_person(UnpairedProcessor(), data)
    assert res.status_code == 200

    with pytest.raises(Exception) as exc_info:
        api.get_user("delete.person")
    assert str(exc_info.value).startswith("404 Client Error: Not Found for url:")

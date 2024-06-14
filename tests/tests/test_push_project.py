"""tests for endpoint 'api/addons/kitsu/{version}/push'
with entities of kitsu type: Project

$ poetry run pytest tests/test_push_project.py
"""

from pprint import pprint

import pytest

from . import mock_data
from .fixtures import (
    PAIR_PROJECT_CODE,
    PAIR_PROJECT_NAME,
    PROJECT_CODE,
    PROJECT_ID,
    PROJECT_NAME,
    api,
    kitsu_url,
    ensure_kitsu_server_setting,
)

from kitsu_mock import KitsuMock


def test_update_project_attrib(
    api, kitsu_url, ensure_kitsu_server_setting, monkeypatch
):
    """update project attrib based on kitsu"""

    entity = mock_data.projects[0]
    project_name = entity["name"]

    api.delete(f"/projects/{project_name}")
    assert not api.get_project(project_name)

    project_meta = {
        "code": entity["code"],
        "data": {"kitsuProjectId": entity["id"]},  # linked to kitsu entity
        "folderTypes": [{"name": "Folder"}],
        "taskTypes": [{"name": "Animation"}],
        "statuses": [{"name": "Todo"}],
    }

    # create the test project
    res = api.put(f"/projects/{project_name}", **project_meta)
    project = api.get_project(project_name)
    print(project["attrib"])

    # lets change the fps
    new_fps = 24.0 if project["attrib"]["fps"] == 25.0 else 25.0

    # change frameStart and frameEnd
    new_frame_start = 2 if project["attrib"]["frameStart"] == 1 else 1
    new_frame_end = 200 if project["attrib"]["frameEnd"] == 100 else 100

    attrib = {"fps": new_fps, "frameStart": new_frame_start, "frameEnd": new_frame_end}

    project = api.update_project(project_name, library=False, attrib=attrib)
    project = api.get_project(project_name)
    print(project)

    assert project["attrib"]["fps"] == new_fps
    assert project["attrib"]["frameStart"] == new_frame_start
    assert project["attrib"]["frameEnd"] == new_frame_end

    res = api.post(
        f"{kitsu_url}/push",
        project_name=entity["name"],
        entities=[entity],
        mock=True,
    )
    assert res.status_code == 200
    project = api.get_project(project_name)

    assert (
        project["attrib"]["fps"] != new_fps
    ), "fps should have been updated from kitsu"

    api.delete(f"/projects/{project_name}")


def test_update_project_statuses(api, kitsu_url, ensure_kitsu_server_setting):
    """update project anatomy based on kitsu data

    we create a project with just 1 status.
    Then when new statuses are added in Kitsu the project.update event is fired.
    Status changes are saved to the project.
    """

    entity = mock_data.projects[0]
    project_name = entity["name"]

    api.delete(f"/projects/{project_name}")
    assert not api.get_project(project_name)

    project_meta = {
        "code": entity["code"],
        "data": {"kitsuProjectId": entity["id"]},  # linked to kitsu entity
        "folderTypes": [{"name": "Folder"}],
        "taskTypes": [{"name": "Animation"}],
        "statuses": [{"name": "Todo"}],
    }

    # create the test project
    res = api.put(f"/projects/{project_name}", **project_meta)

    project = api.get_project(project_name)
    assert project["statuses"] == [{"name": "Todo"}]

    res = api.post(
        f"{kitsu_url}/push",
        project_name=entity["name"],
        entities=[entity],
        mock=True,
    )
    assert res.status_code == 200
    project = api.get_project(project_name)

    assert project["statuses"] == [
        {
            "color": "#f5f5f5",
            "icon": "task_alt",
            "name": "Todo",
            "shortName": "TODO",
            "state": "in_progress",
        },
        {
            "color": "#22D160",
            "icon": "task_alt",
            "name": "Approved",
            "shortName": "App",
            "state": "in_progress",
        },
    ]
    api.delete(f"/projects/{project_name}")


def test_update_project_tasktypes(api, kitsu_url, ensure_kitsu_server_setting):
    """update project anatomy based on kitsu data

    we create a project with just 1 task_type.
    Then when new task types are added in Kitsu the project.update event is fired.
    Ayon project is updated with the new task types.
    """

    entity = mock_data.projects[0]
    project_name = entity["name"]

    api.delete(f"/projects/{project_name}")
    assert not api.get_project(project_name)

    project_meta = {
        "code": entity["code"],
        "data": {"kitsuProjectId": entity["id"]},  # linked to kitsu entity
        "folderTypes": [{"name": "Folder"}],
        "taskTypes": [{"name": "Animation"}],
        "statuses": [{"name": "Todo"}],
    }

    # create the test project
    res = api.put(f"/projects/{project_name}", **project_meta)

    project = api.get_project(project_name)
    assert project["taskTypes"] == [{"name": "Animation"}]

    res = api.post(
        f"{kitsu_url}/push",
        project_name=entity["name"],
        entities=[entity],
        mock=True,
    )
    assert res.status_code == 200
    project = api.get_project(project_name)

    assert project["taskTypes"] == [
        {"icon": "directions_run", "name": "Animation", "shortName": "anim"},
        {"icon": "layers", "name": "Compositing", "shortName": "comp"},
        {"icon": "task_alt", "name": "Grading", "shortName": "Grad"},
    ]
    api.delete(f"/projects/{project_name}")


def test_push_unsynced_project(api, kitsu_url):
    """no update to project that is not synced with kitsu (no matching kitsuProjectId)"""
    entity = mock_data.projects[1]

    project_meta = {
        "code": "ATK",
        "folderTypes": [
            {"name": "Folder"},
            {"name": "Library"},
            {"name": "Asset"},
            {"name": "Episode"},
            {"name": "Sequence"},
            {"name": "Shot"},
        ],
        "taskTypes": [{"name": "Animation"}],
        "statuses": [{"name": "Todo"}],
    }

    # create the 2nd test project
    api.put(f"/projects/{entity['name']}", **project_meta)

    project = api.get_project(entity["name"])
    assert project

    res = api.post(
        f"{kitsu_url}/push",
        project_name=entity["name"],
        entities=[entity],
        mock=True,
    )
    assert res.status_code == 200

    # no project changes as project is not synced
    target_project = api.get_project(entity["name"])
    assert project == target_project

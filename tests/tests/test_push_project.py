""" tests for endpoint 'api/addons/kitsu/{version}/push' 
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
    users,
    users_enabled,
    users_disabled,
)


def test_update_project(api, kitsu_url):
    """update project anatomy based on kitsu data"""
    entity = mock_data.projects[0]

    api.delete(f"/projects/{entity['name']}")
    assert not api.get_project(entity["name"])

    project_meta = {
        "code": "TK",
        "folderTypes": [{"name": "Folder"}],
        "taskTypes": [{"name": "Animation"}],
        "statuses": [{"name": "Todo"}],
    }

    # create the 2nd test project
    api.put(f"/projects/{entity['name']}", **project_meta)

    project = api.get_project(entity["name"])
    assert project["folderTypes"] == [{"name": "Folder"}]
    assert project["taskTypes"] == [{"name": "Animation"}]
    assert project["statuses"] == [{"name": "Todo"}]

    res = api.post(
        f"{kitsu_url}/push",
        project_name=entity["name"],
        entities=[entity],
        mock=True,
    )
    assert res.status_code == 200

    project = api.get_project(entity["name"])

    assert project["folderTypes"] == [
        {"icon": "folder", "name": "Folder", "shortName": ""},
        {"icon": "category", "name": "Library", "shortName": "lib"},
        {"icon": "smart_toy", "name": "Asset", "shortName": ""},
        {"icon": "live_tv", "name": "Episode", "shortName": "ep"},
        {"icon": "theaters", "name": "Sequence", "shortName": "sq"},
        {"icon": "movie", "name": "Shot", "shortName": "sh"},
    ]

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
    assert project["taskTypes"] == [
        {"icon": "directions_run", "name": "Animation", "shortName": "anim"},
        {"icon": "layers", "name": "Compositing", "shortName": "comp"},
        {"icon": "task_alt", "name": "Grading", "shortName": "Grad"},
    ]

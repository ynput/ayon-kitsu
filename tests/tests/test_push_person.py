""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    with entities of kitsu type: Person

    $ poetry run pytest tests/test_push_person.py
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
    users,
    users_enabled,
    users_disabled,
)


def test_push_persons(api, kitsu_url, users, users_enabled):
    """entities of kitsu type: Person

    testkitsu.user1 & testkitsu.user2 already created by the users fixture but have no kitsu_id
    testkitsu.user3 is created by push.py as user does not exist already

    """
    entities = mock_data.all_persons

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    assert "users" in res.data
    assert res.data["users"] == {
        "person-id-1": "testkitsu.user1",
        "person-id-2": "testkitsu.user2",
        "person-id-3": "testkitsu.user3",
    }


def test_push_persons_disabled(api, kitsu_url, users, users_disabled):
    """same as test_push_persons but with
    kitsu addon settings.sync_settings.sync_users.enabled = False

    """
    entities = mock_data.all_persons

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    assert "users" in res.data
    # no users created or updated
    assert res.data["users"] == {}


def test_asignees(api, kitsu_url, users_enabled):
    """check that assignees are correctly"""
    entities = (
        mock_data.all_persons
        + mock_data.all_assets_for_project_preprocessed
        + mock_data.all_episodes_for_project
        + mock_data.all_sequences_for_project
        + mock_data.all_shots_for_project
        + mock_data.all_tasks_for_project_preprocessed
    )

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    tasks = res.data["tasks"]

    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{tasks['task-id-1']}")
    pprint(res.data)
    assert False

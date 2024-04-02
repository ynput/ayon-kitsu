"""tests for endpoint 'api/addons/kitsu/{version}/push'
with entities of kitsu type: Person

$ poetry run pytest tests/test_push_person.py
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
    access_group,
)


def test_push_persons(api, kitsu_url, users, users_enabled, access_group):
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

    # kitsu id should be added to newly CREATED user
    user = api.get_user("testkitsu.user3")
    assert user["data"]["kitsuId"] == "person-id-3"
    assert user["data"]["defaultAccessGroups"] == ["test_kitsu_group"]
    assert user["data"]["accessGroups"] == {"test_kitsu_project": ["test_kitsu_group"]}
    assert user["data"]["isAdmin"] is False
    assert user["data"]["isManager"] is False

    # kitsu id should be added to EXISTING users
    user = api.get_user("testkitsu.user1")
    assert user["data"]["kitsuId"] == "person-id-1"
    assert user["data"]["defaultAccessGroups"] == ["test_kitsu_group"]
    assert user["data"]["accessGroups"] == {"test_kitsu_project": ["test_kitsu_group"]}
    # role is admin (Studio Manager)
    assert user["data"]["isAdmin"] is True
    assert user["data"]["isManager"] is False

    user = api.get_user("testkitsu.user2")
    assert user["data"]["kitsuId"] == "person-id-2"
    assert user["data"]["defaultAccessGroups"] == ["test_kitsu_group"]
    assert user["data"]["accessGroups"] == {"test_kitsu_project": ["test_kitsu_group"]}
    # role is user (Artist)
    assert user["data"]["isAdmin"] is False
    assert user["data"]["isManager"] is True


def test_push_persons_disabled(api, kitsu_url, users, users_disabled, access_group):
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


def test_user_name_change(api, kitsu_url, users_enabled, access_group):
    entities = mock_data.all_persons
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200

    user = mock_data.all_persons[0]

    # ensure user is deleted
    api.delete("/users/testkitsu.newusername")

    # change the name
    user["last_name"] = "New Username"

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[user],
    )
    assert res.status_code == 200
    assert res.data["users"] == {"person-id-1": "testkitsu.newusername"}

    user = api.get_user("testkitsu.newusername")
    assert user["data"]["kitsuId"] == "person-id-1"
    assert user["data"]["defaultAccessGroups"] == ["test_kitsu_group"]

    # check the old user does not exist
    with pytest.raises(Exception):
        user = api.get_user("testkitsu.user1")

    # ensure user is deleted
    api.delete("/users/testkitsu.newusername")


def test_asignees(api, kitsu_url, users_enabled, access_group):
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

    # ayon user names are added as assignees in processor/utils.py
    assert res.data["assignees"] == ["testkitsu.user1", "testkitsu.user3"]


def test_push_bot(api, kitsu_url, users_enabled):
    """test for new API token feature in Kitsu 0.19.2 - Person where is_bot=True"""

    # ensure user is deleted
    api.delete("/users/test.bot")
    bot = {
        "is_bot": True,
        "first_name": "Test",
        "last_name": "Bot",
        "email": "test.bot@studio.com",
        "phone": None,
        "contract_type": "open-ended",
        "active": True,
        "archived": False,
        "last_presence": None,
        "desktop_login": None,
        "login_failed_attemps": 0,
        "last_login_failed": None,
        "totp_enabled": False,
        "email_otp_enabled": False,
        "fido_enabled": False,
        "preferred_two_factor_authentication": None,
        "shotgun_id": None,
        "timezone": "Europe/Paris",
        "locale": "en_US",
        "data": None,
        "role": "admin",
        "has_avatar": True,
        "notifications_enabled": False,
        "notifications_slack_enabled": False,
        "notifications_slack_userid": "",
        "notifications_mattermost_enabled": False,
        "notifications_mattermost_userid": "",
        "notifications_discord_enabled": False,
        "notifications_discord_userid": "",
        "expiration_date": "2024-04-30",
        "is_generated_from_ldap": False,
        "ldap_uid": None,
        "full_name": "Test Bot",
        "id": "bot-id-1",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "type": "Person",
        "fido_devices": [],
    }

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[bot],
    )
    assert res.status_code == 200

    with pytest.raises(Exception) as exc_info:
        api.get_user("test.bot")

    assert (
        str(exc_info.value)
        == "404 Client Error: Not Found for url: http://localhost:5000/api/users/test.bot"
    )
    api.delete("/users/test.bot")

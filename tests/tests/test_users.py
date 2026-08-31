"""tests for endpoint 'api/addons/kitsu/{version}/users'

$ poetry run pytest tests/test_users.py
"""

from .fixtures import (
    PROJECT_NAME,
    access_group,
    api,
    kitsu_url,
    users,
    users_enabled,
)

EXPECTED_KEYS = {"name", "kitsu_id", "email", "full_name", "active"}


def test_list_users_shape(api, kitsu_url, users):
    """The /users endpoint must return the exact fields the processor
    relies on for change detection."""
    res = api.get(f"{kitsu_url}/users")
    assert res.status_code == 200
    assert isinstance(res.data, list)
    assert res.data, "expected at least one AYON user"

    for user in res.data:
        assert set(user.keys()) == EXPECTED_KEYS
        assert isinstance(user["name"], str)
        assert isinstance(user["active"], bool)


def test_list_users_reflects_kitsu_person_sync_fields(
    api, kitsu_url, users_enabled, access_group
):
    """kitsu_id/full_name/email in /users must mirror what /push wrote
    to data.kitsuId / attrib.fullName / attrib.email."""
    entity = {
        "email": "sync.info.user@temp.com",
        "first_name": "Sync",
        "last_name": "InfoUser",
        "full_name": "Sync InfoUser",
        "id": "person-id-sync-info-1",
        "type": "Person",
        "role": "user",
        "active": True,
    }
    api.delete("/users/sync.infouser")

    res = api.post(
        f"{kitsu_url}/push", project_name=PROJECT_NAME, entities=[entity]
    )
    assert res.status_code == 200

    try:
        res = api.get(f"{kitsu_url}/users")
        assert res.status_code == 200

        user = next(u for u in res.data if u["name"] == "sync.infouser")
        assert user["kitsu_id"] == "person-id-sync-info-1"
        assert user["full_name"] == "Sync InfoUser"
        assert user["email"] == "sync.info.user@temp.com"
        assert user["active"] is True
    finally:
        api.delete("/users/sync.infouser")


def test_list_users_includes_inactive_users(
    api, kitsu_url, users_enabled, access_group
):
    """Inactive AYON users must still be returned so Kitsu deactivations
    can be detected and mirrored (see get_user_sync_list docstring)."""
    entity = {
        "email": "inactive.user@temp.com",
        "first_name": "Inactive",
        "last_name": "User",
        "full_name": "Inactive User",
        "id": "person-id-inactive-1",
        "type": "Person",
        "role": "user",
        "active": False,
    }
    api.delete("/users/inactive.user")

    res = api.post(
        f"{kitsu_url}/push", project_name=PROJECT_NAME, entities=[entity]
    )
    assert res.status_code == 200

    try:
        res = api.get(f"{kitsu_url}/users")
        assert res.status_code == 200

        names = {u["name"]: u for u in res.data}
        assert "inactive.user" in names
        assert names["inactive.user"]["active"] is False
    finally:
        api.delete("/users/inactive.user")

"""tests for endpoint 'api/addons/kitsu/{version}/push'
with entities of kitsu type: Person

$ poetry run pytest tests/test_push_person.py
"""

from pprint import pprint

import pytest

from .fixtures import PROJECT_NAME, api, kitsu_url, users_enabled


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

    assert str(exc_info.value).startswith("404 Client Error: Not Found for url:")

    api.delete("/users/test.bot")

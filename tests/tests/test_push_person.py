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


def test_user_names(api, kitsu_url, users, users_enabled, access_group):
    # test for names with special characters
    entities = [
        {
            "email": "user-id-1@temp.com",
            "first_name": "Esbjörn Bøb",
            "full_name": "Esbjörn Bøb Kožušček 1",
            "id": "person-id-0",
            "last_name": "Kožušček 1",
            "type": "Person",
            "role": "user",
        },
    ]

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    assert "users" in res.data
    assert res.data["users"] == {
        "person-id-0": "esbjornbob.kozuscek1",
    }
    user = api.get_user("esbjornbob.kozuscek1")

    assert user["name"] == "esbjornbob.kozuscek1"
    assert user["attrib"]["fullName"] == "Esbjörn Bøb Kožušček 1"
    assert user["data"]["kitsuId"] == "person-id-0"

    # delete the person afterwards
    api.delete("/users/esbjornbob.kozuscek1")

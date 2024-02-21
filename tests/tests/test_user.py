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
    users,
    studio_settings,
)


def test_push_persons(api, kitsu_url, users, studio_settings):
    """entities of kitsu type: Person"""

    entities = mock_data.all_persons

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    pprint(res.data)
    assert False

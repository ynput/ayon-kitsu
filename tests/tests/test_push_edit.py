""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    with entities of kitsu type: Concept

    $ poetry run pytest tests/test_push_concept.py
"""

from pprint import pprint

import pytest

from . import mock_data
from .fixtures import (
    PROJECT_NAME,
    api,
    kitsu_url,
)


def test_push_edits(api, kitsu_url):
    entities = mock_data.all_edits_for_project

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    assert "folders" in res.data
    assert list(res.data["folders"].keys()) == ["edit-id-1", "edit-id-2"]

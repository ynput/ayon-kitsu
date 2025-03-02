"""tests for endpoint 'api/addons/kitsu/{version}/push'
with entities of kitsu type: Edit

$ poetry run pytest tests/test_push_edit.py
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


def test_edit_name_validation_bugfix(api, kitsu_url):
    edit = {
        "id": "edit-id-3",
        "name": "",
        "code": None,
        "description": "",
        "shotgun_id": None,
        "canceled": False,
        "nb_frames": None,
        "nb_entities_out": 0,
        "is_casting_standby": False,
        "status": "running",
        "project_id": "74f89547-91e2-4b91-9fd5-960cc33b30a5",
        "entity_type_id": "65d66965-09c4-45df-857a-112e509db6ef",
        "parent_id": "f998c1ba-4f71-4d7e-b3f4-a1c868709612",
        "source_id": None,
        "preview_file_id": None,
        "data": None,
        "ready_for": None,
        "type": "Edit",
    }

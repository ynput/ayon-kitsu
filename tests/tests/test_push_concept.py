"""tests for endpoint 'api/addons/kitsu/{version}/push'
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


def test_push_concepts(api, kitsu_url):
    entities = mock_data.all_concepts_for_project

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    assert "folders" in res.data
    assert list(res.data["folders"].keys()) == [
        "concept-id-1",
        "concept-id-2",
        "concept-id-3",
    ]


def test_push_concept_tasks(api, kitsu_url):
    entities = mock_data.all_concept_tasks

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=entities,
    )
    assert res.status_code == 200
    pprint(res.data)

    assert "tasks" in res.data
    assert list(res.data["tasks"].keys()) == [
        "concept-task-id-1",
        "concept-task-id-2",
    ]

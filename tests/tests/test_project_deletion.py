"""Project deletion integration tests using disposable AYON projects."""

import os
from copy import deepcopy
from uuid import uuid4

import ayon_api
import pytest
from dotenv import load_dotenv


@pytest.fixture(scope="module")
def deletion_api():
    """Connect without removing or replacing existing projects."""
    load_dotenv()
    api = ayon_api.ServerAPI(
        os.environ.get("AYON_SERVER_URL", "http://localhost:5000"),
        token=os.environ.get("AYON_API_KEY"),
    )
    if not os.environ.get("AYON_API_KEY"):
        api.login("admin", "admin")
    return api


@pytest.fixture(scope="module")
def deletion_endpoint(deletion_api):
    """Select the production addon or an explicitly selected test version."""
    version = os.environ.get("AYON_KITSU_TEST_VERSION")
    if not version:
        response = deletion_api.get("addons")
        response.raise_for_status()
        version = next(
            addon["productionVersion"]
            for addon in response.data["addons"] if addon["name"] == "kitsu"
        )
    assert version, "A Kitsu addon version must be configured"
    return f"addons/kitsu/{version}"


@pytest.fixture
def disposable_project(deletion_api):
    """Create and clean up only a project owned by this test."""
    name = f"kitsu_delete_test_{uuid4().hex}"
    kitsu_id = str(uuid4())
    response = deletion_api.put(
        f"projects/{name}",
        code="KDT",
        data={"kitsuProjectId": kitsu_id},
        folderTypes=[{"name": "Folder"}],
        taskTypes=[{"name": "Animation"}],
        statuses=[{"name": "Todo"}],
    )
    assert response.status_code == 201, response.data
    try:
        yield name, {
            "id": kitsu_id,
            "type": "Project",
            "ayon_server_url": deletion_api.base_url,
        }
    finally:
        response = deletion_api.delete(f"projects/{name}")
        assert response.status_code in (204, 404), response.data


@pytest.fixture
def set_project_deletion(deletion_api, deletion_endpoint):
    """Change the selected addon's setting and restore it after each test."""
    endpoint = f"{deletion_endpoint}/settings"
    response = deletion_api.get(endpoint)
    response.raise_for_status()
    original = deepcopy(response.data)

    def set_enabled(enabled):
        settings = deepcopy(original)
        settings["sync_settings"]["delete_projects"] = enabled
        response = deletion_api.post(endpoint, **settings)
        response.raise_for_status()

    try:
        yield set_enabled
    finally:
        response = deletion_api.post(endpoint, **original)
        response.raise_for_status()


@pytest.mark.parametrize("enabled", [False, True])
def test_project_deletion_setting(
    deletion_api, deletion_endpoint, disposable_project, set_project_deletion,
    enabled,
):
    """The setting decides whether a paired project survives removal."""
    set_project_deletion(enabled)
    name, entity = disposable_project
    response = deletion_api.post(
        f"{deletion_endpoint}/remove", project_name=name, entities=[entity]
    )
    assert response.status_code == 200, response.data
    assert bool(deletion_api.get_project(name)) == (not enabled)
    if enabled:
        response = deletion_api.post(
            f"{deletion_endpoint}/remove", project_name=name, entities=[entity]
        )
        assert response.status_code == 200, response.data


def test_mismatched_project_pairing_is_preserved(
    deletion_api, deletion_endpoint, disposable_project, set_project_deletion,
):
    """An enabled setting cannot delete a project paired to another ID."""
    set_project_deletion(True)
    name, entity = disposable_project
    entity["id"] = str(uuid4())
    response = deletion_api.post(
        f"{deletion_endpoint}/remove", project_name=name, entities=[entity]
    )
    assert response.status_code == 200, response.data
    assert deletion_api.get_project(name)

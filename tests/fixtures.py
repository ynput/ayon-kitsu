import pytest
from .client.api import API

PROJECT_NAME = "test_kitsu_project"
PROJECT_CODE = "TK"
PROJECT_META = {
    "code": PROJECT_CODE,
    "data": {"kitsuProjectId": 'kitsu-project-id-1'},
    "folderTypes": [
        {"name": "Folder"},
        {"name": "Asset"},
    ],
    "taskTypes": [
        {"name": "Generic"},
    ],
    "statuses": [
        {"name": "Unknown"},
    ],
}

@pytest.fixture()
def api():
    print("- api fixture")
    api = API.login("admin", "admin")
    api.delete(f"/projects/{PROJECT_NAME}")
    assert api.put(f"/projects/{PROJECT_NAME}", **PROJECT_META)
    yield api
    api.delete(f"/projects/{PROJECT_NAME}")

    # ensure the synced kitsu project does not exist
    api.delete('/projects/another_test_kitsu_project')
    api.logout()

@pytest.fixture
def kitsu_url(api):
    print("- kitsu fixture")
    """ get the kitsu addon url """

    # /api/addons
    res = api.get("addons")
    assert res.data.get("addons"), "No addons found"

    # map addons list into a dict
    versions = {addon["name"]: addon['productionVersion'] for addon in res.data["addons"]}

    # get the latest version of the addon
    version = versions.get("kitsu")   
    assert version, "Kitsu addon not found"

    # return the addon url
    return f'addons/kitsu/{version}'

    
import os
from pprint import pprint

import ayon_api as _ayon_api
import gazu as _gazu
import pytest
from dotenv import load_dotenv

from . import mock_data

load_dotenv()


PROJECT_NAME = "test_kitsu_project"
PROJECT_ID = "kitsu-project-id-1"
PROJECT_CODE = "TK"
PAIR_PROJECT_NAME = "another_test_kitsu_project"
PAIR_PROJECT_CODE = "ATK"

PROJECT_META = {
    "code": PROJECT_CODE,
    "data": {"kitsuProjectId": PROJECT_ID},
    "folderTypes": [
        {"name": "Folder"},
        {"name": "Library"},
        {"name": "Asset"},
        {"name": "Episode"},
        {"name": "Sequence"},
        {"name": "Shot"},
    ],
    "taskTypes": [
        {"name": "Animation"},
        {"name": "Compositing"},
    ],
    "statuses": [
        {"name": "Todo"},  # the first status is the default
        {"name": "Approved"},
    ],
}


@pytest.fixture(scope="module")
def api():
    """use ayon_api to connect to backend for testing"""

    # set the environment variable for the ayon server if not set
    if "AYON_SERVER_URL" not in os.environ:
        os.environ["AYON_SERVER_URL"] = "http://localhost:5000"

    api = _ayon_api.GlobalServerAPI()
    if "AYON_API_KEY" not in os.environ:
        api.login("admin", "admin")
    else:
        _ayon_api.init_service()
    api.delete(f"/projects/{PROJECT_NAME}")
    assert api.put(f"/projects/{PROJECT_NAME}", **PROJECT_META)
    yield api
    api.delete(f"/projects/{PROJECT_NAME}")

    # ensure the synced kitsu project does not exist
    api.delete(f"/projects/{PAIR_PROJECT_NAME}")
    api.logout()


@pytest.fixture(scope="module")
def kitsu_url(api):
    """get the kitsu addon url"""

    # /api/addons
    res = api.get("addons")
    assert res.data.get("addons"), "No addons found"

    # map addons list into a dict
    versions = {
        addon["name"]: addon["productionVersion"] for addon in res.data["addons"]
    }

    # get the latest version of the addon
    version = versions.get("kitsu")
    assert version, "Kitsu addon not found"

    # return the addon url
    return f"addons/kitsu/{version}"


@pytest.fixture(scope="module")
def init_data(api, kitsu_url):
    # create the starting entities
    entities = (
        mock_data.all_assets_for_project_preprocessed
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
    print("init_data...")
    pprint(res.data)
    assert res.status_code == 200


@pytest.fixture(scope="module")
def gazu():
    # host = os.environ.get('KITSU_API_URL', 'http://localhost/api')
    # login = os.environ.get('KITSU_LOGIN', 'admin@example.com')
    # pwd = os.environ.get('KITSU_PWD', 'mysecretpassword')

    # ## optional login to live kitsu
    # print(f"gazu logging into {host} with {login}")
    # _gazu.set_host(host)
    # _gazu.log_in(login, pwd)

    return _gazu


@pytest.fixture(scope="module")
def processor(kitsu_url):
    class MockProcessor:
        entrypoint = kitsu_url

        def get_paired_ayon_project(self, kitsu_project_id):
            return PROJECT_NAME

    return MockProcessor()


@pytest.fixture()
def ensure_kitsu_server_setting(api, kitsu_url):
    """update kitsu addon settings.kitsu_server if not set"""
    # lets get the settings for the addon
    res = api.get(f"{kitsu_url}/settings")
    assert res.status_code == 200
    settings = res.data

    # get original values
    value = settings["server"]

    # set settings for tests
    if not value:
        settings["server"] = "http://kitsu.com"
        res = api.post(f"{kitsu_url}/settings", **settings)

    yield

    # set settings back to orginal values
    if not value:
        settings["server"] = ""
        res = api.post(f"{kitsu_url}/settings", **settings)

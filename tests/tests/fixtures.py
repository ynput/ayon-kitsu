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
USER1_NAME = "testkitsu.user1"
USER2_NAME = "testkitsu.user2"
USER3_NAME = "testkitsu.user3"

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
def users(api, kitsu_url):
    """create ayon users"""
    api.delete(f"/users/{USER1_NAME}")
    api.delete(f"/users/{USER2_NAME}")
    api.delete(f"/users/{USER3_NAME}")

    # only create 2 users so the other one can be created if missing
    api.put(f"/users/{USER1_NAME}")
    api.put(f"/users/{USER2_NAME}")
    print(f"created user: {USER1_NAME}")
    print(f"created user: {USER2_NAME}")

    yield

    api.delete(f"/users/{USER1_NAME}")
    api.delete(f"/users/{USER2_NAME}")
    api.delete(f"/users/{USER3_NAME}")

    # ensure renamed user is deleted
    api.delete("/users/testkitsu.newusername")


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



# ======= Studio Settings Fixtures ==========
@pytest.fixture()
def ensure_kitsu_server_setting(api, kitsu_url):
    """update kitsu addon settings.kitsu_server if not set"""
    res = api.get(f"{kitsu_url}/settings")
    assert res.status_code == 200
    settings = res.data
    
    value = settings["server"]

    # set settings for tests
    if not value:
        settings["server"] = "http://kitsu.com"
        res = api.post(f"{kitsu_url}/settings", **settings)

    yield

    if not value:
        settings["server"] = ""
        res = api.post(f"{kitsu_url}/settings", **settings)

@pytest.fixture()
def users_enabled(api, kitsu_url):
    """update kitsu addon settings.sync_settings.sync_users.enabled"""
    # lets get the settings for the addon
    res = api.get(f"{kitsu_url}/settings")
    assert res.status_code == 200
    settings = res.data

    # get original values
    users_enabled = settings["sync_settings"]["sync_users"]["enabled"]

    # set settings for tests
    if not users_enabled:
        settings["sync_settings"]["sync_users"]["enabled"] = True
        res = api.post(f"{kitsu_url}/settings", **settings)

    yield

    # set settings back to orginal values
    if not users_enabled:
        settings["sync_settings"]["sync_users"]["enabled"] = users_enabled
        res = api.post(f"{kitsu_url}/settings", **settings)


@pytest.fixture()
def users_disabled(api, kitsu_url):
    """update kitsu addon settings.sync_settings.sync_users.enabled"""

    # lets get the settings for the addon
    res = api.get(f"{kitsu_url}/settings")
    assert res.status_code == 200
    settings = res.data

    # get original values

    value = settings["sync_settings"]["sync_users"]["enabled"]
    print(f"users_disabled: {value}")

    # set settings for tests
    if value:
        settings["sync_settings"]["sync_users"]["enabled"] = False
        res = api.post(f"{kitsu_url}/settings", **settings)

    yield

    if value:
        settings["sync_settings"]["sync_users"]["enabled"] = value
        res = api.post(f"{kitsu_url}/settings", **settings)


@pytest.fixture()
def access_group(api, kitsu_url):
    """update kitsu addon settings.sync_settings.sync_users.access_group"""

    # lets get the settings for the addon
    res = api.get(f"{kitsu_url}/settings")
    assert res.status_code == 200
    settings = res.data

    # get original values
    value = settings["sync_settings"]["sync_users"]["access_group"]

    # set settings for tests
    if value != "test_kitsu_group":
        settings["sync_settings"]["sync_users"]["access_group"] = "test_kitsu_group"
        res = api.post(f"{kitsu_url}/settings", **settings)

    yield

    # set settings back to orginal values
    if value != "test_kitsu_group":
        settings["sync_settings"]["sync_users"]["access_group"] = value
        res = api.post(f"{kitsu_url}/settings", **settings)


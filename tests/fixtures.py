import pytest
import os
import gazu as _gazu
import ayon_api as _ayon_api


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
        {"name": "Todo"}, # the first status is the default
        {"name": "Approved"},
    ],
}
@pytest.fixture(scope="session")
def api():
    """ use ayon_api to connect to backend for testing """

    # set the environment variable for the ayon server if not set
    if 'AYON_SERVER_URL' not in os.environ:
        os.environ['AYON_SERVER_URL'] = "http://localhost:5000"

    api = _ayon_api.GlobalServerAPI()
    api.login("admin", "admin")
    api.delete(f"/projects/{PROJECT_NAME}")
    assert api.put(f"/projects/{PROJECT_NAME}", **PROJECT_META)
    yield api
    api.delete(f"/projects/{PROJECT_NAME}")

    # ensure the synced kitsu project does not exist
    api.delete(f'/projects/{PAIR_PROJECT_NAME}')
    api.logout()

@pytest.fixture
def kitsu_url(api, scope="session"):
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

@pytest.fixture
def gazu():

    host = os.environ.get('KITSU_API_URL', 'http://localhost/api')
    login = os.environ.get('KITSU_LOGIN', 'admin@example.com')
    pwd = os.environ.get('KITSU_PWD', 'mysecretpassword')

    ## optional login to live kitsu 
    # _gazu.set_host(host)
    # _gazu.log_in(login, pwd)

    return _gazu

@pytest.fixture
def processor():
    class MockProcessor:
        entrypoint = "/addons/kitsu/x.x.x"
    
    return MockProcessor()
    
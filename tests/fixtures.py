import pytest
import os
from pprint import pprint
import gazu as _gazu
import ayon_api as _ayon_api

from . import mock_data


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
        { 'name': "Todo" }, # the first status is the default
        {"name": "Approved" },
    ],
}
@pytest.fixture(scope="module")
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

@pytest.fixture(scope="module")
def kitsu_url(api):
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

@pytest.fixture(scope="module")
def init_data(api, kitsu_url):
    # create the starting entities
    entities =  (
        mock_data.all_assets_for_project_preprocessed + 
        mock_data.all_episodes_for_project + 
        mock_data.all_sequences_for_project + 
        mock_data.all_shots_for_project +
        mock_data.all_tasks_for_project_preprocessed
    )
    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=entities,
    )
    pprint(res.data)
    assert res.status_code == 200


@pytest.fixture(scope="module")
def gazu():

    host = os.environ.get('KITSU_API_URL', 'http://localhost/api')
    login = os.environ.get('KITSU_LOGIN', 'admin@example.com')
    pwd = os.environ.get('KITSU_PWD', 'mysecretpassword')

    # ## optional login to live kitsu 
    # print(f"gazu logging into {host} with {login}")
    # _gazu.set_host(host)
    # _gazu.log_in(login, pwd)

    return _gazu

@pytest.fixture(scope="module")
def processor(kitsu_url):
    class MockProcessor:
        entrypoint = kitsu_url
    
    return MockProcessor()


    
from .fixtures import api, kitsu_url, init_data, PROJECT_NAME

from . import mock_data
from pprint import pprint

""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    deleting entities

    $ poetry run pytest tests/test_push_delete.py
"""

def test_delete_episode(api, kitsu_url, init_data):
    # d
    kitsu_id = 'episode-id-1'

    # just id and type are required
    entity = {
        'id':    kitsu_id,      # required
        'type': 'Episode',      # required
    }
    res = api.delete(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=[entity],
    )
    assert res.status_code == 200
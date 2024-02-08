from .fixtures import api, kitsu_url, init_data, PROJECT_NAME

from . import mock_data
from pprint import pprint

""" tests for endpoint 'api/addons/kitsu/{version}/remove' 
    removing entities

    $ poetry run pytest tests/test_push_remove.py
"""

def test_remove_episode(init_data, api, kitsu_url):

    pprint(api.get_folders_hierarchy(PROJECT_NAME))

    # just id and type are required
    entity = {
        'id':    'episode-id-1', 
        'type': 'Episode',        
    }
    res = api.post(
        f'{kitsu_url}/remove', 
        project_name=PROJECT_NAME,
        entities=[entity]
    )
    pprint(res.data)
    assert res.status_code == 200

    # does the folder delete remove all sub folders?
    pprint(api.get_folders_hierarchy(PROJECT_NAME))


def test_remove_shot(api, kitsu_url):
    entity = {
        'id':    'shot-id-1', 
        'type': 'Shot',        
    }
    res = api.post(
        f'{kitsu_url}/remove', 
        project_name=PROJECT_NAME,
        entities=[entity]
    )
    assert res.status_code == 200

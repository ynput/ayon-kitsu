
from .fixtures import api, kitsu_url, PROJECT_NAME

from . import mock_data
from pprint import pprint

""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    updating entities with changes

    $ poetry run pytest tests/test_push_update.py
"""


def test_update_folder(api, kitsu_url):

    # create the first entity
    episode_entity = mock_data.all_episodes_for_project[0]
    episode_entity['name'] = "my_episode"
    episode_entity['label'] = "My Episode"

    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=[episode_entity],
    )
    assert res.status_code == 200
    assert res.data, "push should return the ayon objects created including the ayon id"

    # do a partial update
    update = {
        "id": episode_entity['id'],  # required
        "type": "Episode",           # required
        "name": "my_updated_name",
        "label": "My Updated Label",
        
    }
    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=[update],
    )
    assert res.data, "push should return the ayon objects updated including the ayon id"
    pprint(res.data)
    assert res.status_code == 200

    res = api.get_folder_by_kitsu_id(PROJECT_NAME, episode_entity['id'])
    pprint(res.data)

    assert False


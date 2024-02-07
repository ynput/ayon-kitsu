from .fixtures import api, kitsu_url, init_data, PROJECT_NAME

from . import mock_data
from pprint import pprint

""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    updating entities with changes

    $ poetry run pytest tests/test_push_update.py
"""
def test_update_shot_data(api, kitsu_url, init_data):

    # do a partial update
    kitsu_id = 'shot-id-1'
    update = {
        'id': kitsu_id,      # required
        'type': 'Shot',      # required
        'name': "SH001",
        'data': {
            "fps": "24",            # 25 => 24
            "frame_in": "2",        # 0 => 1
            "frame_out": "102"      # 100 => 102
        }
    }
    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=[update],
    )
   
    # res.data should be maps of kitsu-ids to ayon-ids {'folders': {'shot-id-1': '40dfcf00c50511eeba890242ac150004'}, 'tasks': {}}
    assert res.data, "push should return the ayon objects created including the ayon id"
    assert kitsu_id in res.data['folders']
    assert isinstance(res.data['folders'][kitsu_id], str)
    assert res.data['tasks'] == {}

    # lets get the ayon folder
    ayon_id = res.data['folders'][kitsu_id]
    folder = api.get_folder_by_id(PROJECT_NAME, ayon_id)
    pprint(folder)

    # fps and frame_in should be updated
    assert folder['attrib']['fps'] == 24
    assert folder['attrib']['frameStart'] == 2
    assert folder['attrib']['frameEnd'] == 102
    
 
def test_update_folder_name(api, kitsu_url):

    # do a partial update
    kitsu_id = 'shot-id-1'
    update = {
        "id": kitsu_id,         # required
        "type": "Episode",      # required
        "name": "An Updated Name!",
    }
    res = api.post(
        f'{kitsu_url}/push', 
        project_name=PROJECT_NAME,
        entities=[update],
    )

    # lets get the ayon folder
    ayon_id = res.data['folders'][kitsu_id]
    folder = api.get_folder_by_id(PROJECT_NAME, ayon_id)

    assert folder['name'] == "an_updated_name"
    assert folder['label'] == "An Updated Name!"
   

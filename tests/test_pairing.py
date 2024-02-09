from tests.fixtures import (
    api, 
    kitsu_url, 
    PROJECT_NAME, PROJECT_CODE, 
    PAIR_PROJECT_NAME, PAIR_PROJECT_CODE
)

from pprint import pprint


""" tests for endpoint 'api/addons/kitsu/{version}/pairing' 

    $ poetry run pytest tests/test_pairing.py
"""

def test_get_pairing(api, kitsu_url):

    # ensure the kitsu project does not exist
    api.delete(f'/projects/{PAIR_PROJECT_NAME}')
    
    res = api.get(f'{kitsu_url}/pairing', mock=True)
    assert res.status_code == 200
    pprint(res.data)
    assert res.data == [
        {'kitsuProjectId': 'kitsu-project-id-1', 'kitsuProjectName': 'Kitsu Test Project', 'kitsuProjectCode': 'KTP', 'ayonProjectName': PROJECT_NAME}, 
        {'kitsuProjectId': 'kitsu-project-id-2', 'kitsuProjectName': 'Another Project', 'kitsuProjectCode': 'AP', 'ayonProjectName': None}
    ]

def _test_post_pairing_success(api, kitsu_url):

    res = api.post(
        f'{kitsu_url}/pairing', 
        kitsuProjectId='kitsu-project-id-2', 
        ayonProjectName=PAIR_PROJECT_NAME,
        ayonProjectCode=PAIR_PROJECT_CODE,
        mock=True
    )
    assert res.status_code == 201 # created
    
    res = api.get(f'projects/{PAIR_PROJECT_NAME}')
    project = res.data

    # check the created project
    assert project['name'] == PAIR_PROJECT_NAME
    assert project['code'] == PAIR_PROJECT_CODE
    assert project['data'] == {'kitsuProjectId': 'kitsu-project-id-2'}
    assert project['active']

    # task types
    assert project['taskTypes'][0] == {
        'name': "Animation",
        'shortName': "anim",
        'icon': 'directions_run'
    }
    assert project['taskTypes'][1] == {
        'name': "Compositing",
        'shortName': "comp",
        'icon': 'layers'
    }
    
    # statuses
    assert project['statuses'][0] == {
        'name': "Todo",
        'color': "#f5f5f5",
        'state':"in_progress", 
        'shortName': "TODO",
        'icon': '',
    }

    assert project['statuses'][1] == {
        'name': "Approved",
        'color': "#22D160",
        'state':"in_progress", 
        'shortName': "App",
        'icon': '',
    }

    assert project['tags'] == [] # could be useful for kitsu info

    assert project['attrib'] == {
        'fps': 25.0,
        'resolutionWidth': 1920,
        'resolutionHeight': 1080,
        'pixelAspect': 1.0,
        'clipIn': 1,
        'clipOut': 1,
        'frameStart': 1001,
        'frameEnd': 1001,
        'handleStart': 0,
        'handleEnd': 0,
        'startDate': '2024-01-01T00:00:00+00:00',
        'endDate': '2024-12-31T00:00:00+00:00'
    }

    assert project['folderTypes'] == [
        {'icon': 'folder', 'name': 'Folder', 'shortName': ''},
        {'icon': 'category', 'name': 'Library', 'shortName': 'lib'},
        {'icon': 'smart_toy', 'name': 'Asset', 'shortName': ''},
        {'icon': 'live_tv', 'name': 'Episode', 'shortName': 'ep'},
        {'icon': 'theaters', 'name': 'Sequence', 'shortName': 'sq'},
        {'icon': 'movie', 'name': 'Shot', 'shortName': 'sh'}
    ]

    assert project['ownAttrib'] == [
        'fps',
        'clipIn',
        'clipOut',
        'endDate',
        'frameEnd',
        'handleEnd',
        'startDate',
        'frameStart',
        'handleStart',
        'pixelAspect',
        'resolutionWidth',
        'resolutionHeight'
    ]

    # the pairing should be updated
    res = api.get(f'{kitsu_url}/pairing', mock=True)
    assert res.status_code == 200
    
    assert res.data == [
        {'kitsuProjectId': 'kitsu-project-id-1', 'kitsuProjectName': 'Kitsu Test Project', 'kitsuProjectCode': 'KTP', 'ayonProjectName': 'test_kitsu_project'}, 
        {'kitsuProjectId': 'kitsu-project-id-2', 'kitsuProjectName': 'Another Project', 'kitsuProjectCode': 'AP', 'ayonProjectName': PAIR_PROJECT_NAME}
    ]


def _test_post_pairing_already_exists(api, kitsu_url):
    """ should have conflict if ayon project is already paired """

    res = api.post(
        f'{kitsu_url}/pairing', 
        kitsuProjectId='kitsu-project-id-2', 
        ayonProjectName=PROJECT_NAME,
        ayonProjectCode=PROJECT_CODE
    )
    assert res.status_code == 409 # conflict

# def test_post_pairing_duplicate(api, kitsu_url):
#     """ should not be able to pair the same kitsu project with multiple ayon projects """

#     res = api.post(
#         f'{kitsu_url}/pairing', 
#         kitsuProjectId='kitsu-project-id-2', 
#         ayonProjectName=PAIR_PROJECT_NAME,
#         ayonProjectCode=PAIR_PROJECT_CODE
#     )
#     res = api.post(
#         f'{kitsu_url}/pairing', 
#         kitsuProjectId='kitsu-project-id-2', 
#         ayonProjectName="some_other_name",
#         ayonProjectCode="SON"
#     )
#     api.delete(f'/projects/some_other_name')

#     assert res.status_code != 201 

    

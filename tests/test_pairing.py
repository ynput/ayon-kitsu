from tests.fixtures import api, kitsu_url, PROJECT_NAME, PROJECT_CODE

assert api


""" tests for endpoint 'api/addons/kitsu/{version}/pairing' """

def test_get_pairing(api, kitsu_url):

    # ensure the kitsu project does not exist
    api.delete('/projects/another_test_kitsu_project')
    
   
    res = api.get(f'{kitsu_url}/pairing', mock=True)
    
    assert res.data == [
        {'kitsuProjectId': 'kitsu-project-id-1', 'kitsuProjectName': 'Kitsu Test Project', 'kitsuProjectCode': 'KTP', 'ayonProjectName': 'test_kitsu_project'}, 
        {'kitsuProjectId': 'kitsu-project-id-2', 'kitsuProjectName': 'Another Project', 'kitsuProjectCode': 'AP', 'ayonProjectName': None}
    ]

def test_post_pairing_success(api, kitsu_url):

    project_name = 'another_test_kitsu_project'
    res = api.post(
        f'{kitsu_url}/pairing', 
        kitsuProjectId='kitsu-project-id-2', 
        ayonProjectName=project_name,
        ayonProjectCode='AP',
        mock=True
    )
    
    res = api.get(f'projects/{project_name}')
    project = res.data

    # check the created project
    assert project['name'] == project_name
    assert project['code'] == 'AP'
    assert project['data'] == {'kitsuProjectId': 'kitsu-project-id-2'}
    assert project['active']

    assert project['taskTypes'][0]['name'] == "Animation"
    assert project['taskTypes'][0]['shortName'] == "anim"
    assert project['taskTypes'][1]['name'] == "Compositing"
    assert project['taskTypes'][1]['shortName'] == "comp"

    assert project['statuses'][0]['name'] == "Todo"
    assert project['statuses'][0]['color'] == "#f5f5f5"
    assert project['statuses'][0]['state'] == "in_progress" ## why in_progress?
    assert project['statuses'][0]['shortName'] == "TODO"

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

    # the pairing should be updated
    res = api.get(f'{kitsu_url}/pairing', mock=True)
    
    assert res.data == [
        {'kitsuProjectId': 'kitsu-project-id-1', 'kitsuProjectName': 'Kitsu Test Project', 'kitsuProjectCode': 'KTP', 'ayonProjectName': 'test_kitsu_project'}, 
        {'kitsuProjectId': 'kitsu-project-id-2', 'kitsuProjectName': 'Another Project', 'kitsuProjectCode': 'AP', 'ayonProjectName': project_name}
    ]


 

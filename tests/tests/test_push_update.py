from pprint import pprint

from . import mock_data
from .fixtures import PROJECT_NAME, api, init_data, kitsu_url

""" tests for endpoint 'api/addons/kitsu/{version}/push' 
    updating entities with changes

    $ poetry run pytest tests/test_push_update.py
"""


def test_update_folder_attrib(api, kitsu_url, init_data):
    # do a partial update
    kitsu_id = "shot-id-1"
    update = {
        "id": kitsu_id,  # required
        "type": "Shot",  # required
        "name": "SH001",
        "data": {
            "fps": "24",  # 25 => 24
            "frame_in": "2",  # 0 => 1
            "frame_out": "102",  # 100 => 102
        },
    }
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[update],
    )
    assert res.status_code == 200

    # res.data should be maps of kitsu-ids to ayon-ids such as
    # {'folders': {'shot-id-1': '40dfcf00c50511eeba890242ac150004'}, 'tasks': {}}
    assert res.data, "push should return the ayon objects created including the ayon id"
    assert kitsu_id in res.data["folders"]
    assert isinstance(res.data["folders"][kitsu_id], str)
    assert res.data["tasks"] == {}

    # lets get the ayon folder
    ayon_id = res.data["folders"][kitsu_id]
    folder = api.get_folder_by_id(PROJECT_NAME, ayon_id)

    # fps and frame_in should be updated
    assert folder["attrib"]["fps"] == 24
    assert folder["attrib"]["frameStart"] == 2
    assert folder["attrib"]["frameEnd"] == 102


def test_update_folder_name(api, kitsu_url):
    # do a partial update
    kitsu_id = "shot-id-1"
    update = {
        "id": kitsu_id,  # required
        "type": "Shot",  # required
        "name": "An Updated Name!",  # required
    }
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[update],
    )

    # lets get the ayon folder
    ayon_id = res.data["folders"][kitsu_id]
    folder = api.get_folder_by_id(PROJECT_NAME, ayon_id)

    assert folder["name"] == "an_updated_name"
    assert folder["label"] == "An Updated Name!"


def test_update_folder_no_changes(api, kitsu_url):
    # do a partial update
    kitsu_id = "shot-id-1"
    update = {
        "id": kitsu_id,  # required
        "type": "Shot",  # required
        "name": "An Updated Name!",  # no change
        "ready_for": "animation",  # update a key that does not get updated in ayon
    }
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[update],
    )
    assert res.status_code == 200

    # there should be no folders returned as none were created or updated
    assert res.data["folders"] == {}


def test_update_task_status(api, kitsu_url):
    # do a partial update
    kitsu_id = "task-id-1"
    update = {
        "id": kitsu_id,  # required
        "type": "Task",  # required
        "name": "animation",  # required
        "task_status_name": "Approved",  # Todo -> Approved
    }
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[update],
    )
    task_id = res.data["tasks"][kitsu_id]

    # note: ayon_api.get_task(project_name, task_id) does not include the status, not sure why
    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{task_id}")
    assert res.status_code == 200
    task = res.data
    assert task["status"] == "Approved"


def test_update_task_no_changes(api, kitsu_url):
    # do a partial update
    kitsu_id = "task-id-1"
    update = {
        "id": kitsu_id,  # required
        "type": "Task",  # required
        "name": "animation",  # no change
        "ready_for": "animation",  # update a key that does not get updated in ayon
    }
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[update],
    )
    assert res.status_code == 200

    # there should be no tasks returned as none were created or updated
    assert res.data["tasks"] == {}


def test_update_task_with_new_status(api, kitsu_url):
    # do a partial update
    kitsu_id = "task-id-1"
    update = {
        "id": kitsu_id,  # required
        "type": "Task",  # required
        "name": "animation",  # required
        "task_status_name": "New Status",  # Approved -> New Status
    }
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[update],
    )
    pprint(res.data)
    ayon_id = res.data["tasks"][kitsu_id]

    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{ayon_id}")
    assert res.status_code == 200
    folder = res.data
    assert folder["status"] == "New Status"

    # check the status has been created
    res = api.get(f"/projects/{PROJECT_NAME}")
    assert "New Status" in [s["name"] for s in res.data["statuses"]]


def test_update_task_with_new_type(api, kitsu_url):
    # do a partial update
    kitsu_id = "task-id-1"
    update = {
        "id": kitsu_id,  # required
        "type": "Task",  # required
        "name": "new_type",  # required
        "task_type_name": "New Type",
    }
    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[update],
    )
    ayon_id = res.data["tasks"][kitsu_id]

    res = api.get(f"/projects/{PROJECT_NAME}/tasks/{ayon_id}")
    assert res.status_code == 200
    folder = res.data
    assert folder["taskType"] == "New Type"

    # check the type has been created
    res = api.get(f"/projects/{PROJECT_NAME}")
    assert "New Type" in [t["name"] for t in res.data["taskTypes"]]

from processor import fullsync
from nxtools import logging
import ayon_api

from .fixtures import gazu, processor, PROJECT_ID, PROJECT_NAME

from . import mock_data

""" tests for services/processor/fullsync.py

    $ poetry run pytest tests/test_fullsync.py 
"""

def test_get_asset_types(gazu, monkeypatch):

    monkeypatch.setattr(
        gazu.asset, 
        'all_asset_types_for_project', 
        lambda x: mock_data.all_asset_types_for_project
    )
    res = fullsync.get_asset_types(PROJECT_ID)
 
    assert res == {
        'asset-type-id-1': 'Character', 
        'asset-type-id-2': 'Rig', 
        'asset-type-id-3': 'Location'
    }

    # # archived asset_types should be excluded??
    # data[0]['archived'] == True
    # monkeypatch.setattr(gazu.asset, 'all_asset_types_for_project', lambda x: data)
 
    # asset_types = fullsync.get_asset_types(PROJECT_ID)
 
    # assert asset_types == { 'id-2': 'Rig', 'id-3': 'Location'}

def test_get_task_types(gazu, monkeypatch):

    monkeypatch.setattr(
        gazu.task, 
        'all_task_types_for_project', 
        lambda x: mock_data.all_task_types_for_project
    )
    res = fullsync.get_task_types(PROJECT_ID)
    assert res == {'task-type-id-1': 'Animation', 'task-type-id-2': 'Compositing'}


def test_get_statuses(gazu, monkeypatch):

    monkeypatch.setattr(
        gazu.task, 
        'all_task_statuses', 
        lambda: mock_data.all_task_statuses
    )
    res = fullsync.get_statuses()
    assert res == {'task-status-id-1': 'Todo', 'task-status-id-2': 'Approved'}

def test_get_assets(gazu, monkeypatch):
    monkeypatch.setattr(
        gazu.asset, 
        'all_assets_for_project', 
        lambda x: mock_data.all_assets_for_project
    )
    res = fullsync.get_assets(PROJECT_ID,  {
        'asset-type-id-1': 'Character', 
        'asset-type-id-2': 'Rig', 
        'asset-type-id-3': 'Location'
    })
    assert len(res) == 2
    assert res[0]['id'] == "asset-id-1"
    assert res[0]['asset_type_name'] == 'Character'

    assert res[1]['id'] == "asset-id-2"
    assert res[1]['asset_type_name'] == 'Rig'


def test_get_tasks(gazu, monkeypatch):
    monkeypatch.setattr(
        gazu.task, 
        'all_tasks_for_project', 
        lambda x: mock_data.all_tasks_for_project
    )
    res = fullsync.get_tasks(
        PROJECT_ID,  
        {'task-type-id-1': 'Animation', 'task-type-id-2': 'Compositing'},
        {'task-status-id-1': 'Todo', 'task-status-id-2': 'Approved'}
    )
    assert len(res) == 2
    assert res[0]['id'] == "task-id-1"
    assert res[0]['task_type_name'] == 'Animation'
    assert res[0]['task_status_name'] == 'Approved'

    assert res[1]['id'] == "task-id-2"
    assert res[1]['task_type_name'] == 'Compositing'
    assert res[1]['task_status_name'] == 'Todo'
    

def test_full_sync(gazu, processor, monkeypatch, mocker):

    # mock all kitsu data coming from gazu
    monkeypatch.setattr(
        gazu.task, 
        'all_task_types_for_project', 
        lambda x: mock_data.all_task_types_for_project
    )
    monkeypatch.setattr(
        gazu.asset, 
        'all_asset_types_for_project', 
        lambda x: mock_data.all_asset_types_for_project
    )
    monkeypatch.setattr(
        gazu.task, 
        'all_task_statuses', 
        lambda: mock_data.all_task_statuses
    )
    monkeypatch.setattr(
        gazu.shot, 
        'all_episodes_for_project', 
        lambda x: mock_data.all_episodes_for_project
    )
    monkeypatch.setattr(
        gazu.shot,
        'all_sequences_for_project',
        lambda x: mock_data.all_sequences_for_project
    )
    monkeypatch.setattr(
        gazu.shot,
        'all_shots_for_project',
        lambda x: mock_data.all_shots_for_project
    )
    monkeypatch.setattr(
        gazu.asset,
        'all_assets_for_project',
        lambda x: mock_data.all_assets_for_project
    )
    monkeypatch.setattr(
        gazu.task,
        'all_tasks_for_project',
        lambda x: mock_data.all_tasks_for_project
    )

    # mocker patches
    log_info = mocker.patch.object(logging, 'info')
    api_patch = mocker.patch.object(ayon_api, 'post')
    
    processor.entrypoint = "/addons/kitsu/9.9.9"
    res = fullsync.full_sync(processor, PROJECT_ID, "AYON_Project")

    # assert logging
    log_info.assert_called_once_with(f"Syncing kitsu project {PROJECT_ID} to AYON_Project")
    
    # assert ayon api call
    api_patch.assert_called_once()
    args = api_patch.call_args.args
    kwargs = api_patch.call_args.kwargs

    assert args[0] == '/addons/kitsu/9.9.9/push'
    assert kwargs['project_name'] == 'AYON_Project'
    assert len(kwargs['entities'] ) == 11

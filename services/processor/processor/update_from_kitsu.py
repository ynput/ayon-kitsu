from typing import TYPE_CHECKING

import ayon_api
import gazu
from . import utils
from nxtools import logging

if TYPE_CHECKING:
    from .kitsu import KitsuProcessor

def create_or_update_asset(parent: "KitsuProcessor", data):
    logging.info(f'create_or_update_asset: {data}')
    # Get asset entity
    asset = gazu.asset.get_asset(data["asset_id"])
    asset = utils.preprocess_asset(asset['project_id'], asset)

    
    res = ayon_api.post(
        f'{parent.entrypoint}/push', 
        project_name="test_kitsu_project",
        entities=[asset],
    )
    logging.info(f'ayon_api.post {parent.entrypoint}/push: {res.status_code} {res.data}')
    return res

 
def delete_asset(parent: "KitsuProcessor", data):
    logging.info(f'delete_asset: {data}')
    entity = {
        'id':  data['asset_id'], 
        'type': 'Asset',        
    }
    return ayon_api.post(
        f'{parent.entrypoint}/remove', 
        project_name="test_kitsu_project",
        entities=[entity],
    )

def create_or_update_episode(parent: "KitsuProcessor", data):
    logging.info(f'create_or_update_episode: {data}')
    # Get episode entity
    episode = gazu.shot.get_episode(data["episode_id"])
  
    return ayon_api.post(
        f'{parent.entrypoint}/push', 
        project_name="test_kitsu_project",
        entities=[episode],
    )
 
def delete_episode(parent: "KitsuProcessor", data):
    logging.info(f'delete_episode: {data}')
    entity = {
        'id':  data['episode_id'], 
        'type': 'Episode',        
    }
    return ayon_api.post(
        f'{parent.entrypoint}/remove', 
        project_name="test_kitsu_project",
        entities=[entity],
    )

def create_or_update_sequence(parent: "KitsuProcessor", data):
    logging.info(f'create_or_update_sequence: {data}')
    sequence = gazu.shot.get_sequence(data["sequence_id"])
  
    return ayon_api.post(
        f'{parent.entrypoint}/push', 
        project_name="test_kitsu_project",
        entities=[sequence],
    )
 
def delete_sequence(parent: "KitsuProcessor", data):
    logging.info(f'delete_sequence: {data}')
    entity = {
        'id':  data['sequence_id'], 
        'type': 'Sequence',        
    }
    return ayon_api.post(
        f'{parent.entrypoint}/remove', 
        project_name="test_kitsu_project",
        entities=[entity],
    )

def create_or_update_shot(parent: "KitsuProcessor", data):
    logging.info(f'create_or_update_shot: {data}')
    shot = gazu.shot.get_shot(data["shot_id"])
  
    return ayon_api.post(
        f'{parent.entrypoint}/push', 
        project_name="test_kitsu_project",
        entities=[shot],
    )
 
def delete_shot(parent: "KitsuProcessor", data):
    logging.info(f'delete_shot: {data}')
    entity = {
        'id':  data['shot_id'], 
        'type': 'Shot',        
    }
    return ayon_api.post(
        f'{parent.entrypoint}/remove', 
        project_name="test_kitsu_project",
        entities=[entity],
    )

def create_or_update_task(parent: "KitsuProcessor", data):
    logging.info(f'create_or_update_task: {data}')
    
    task = gazu.task.get_task(data["task_id"])
    task = utils.preprocess_task(task['project_id'], task)
  
    return ayon_api.post(
        f'{parent.entrypoint}/push', 
        project_name="test_kitsu_project",
        entities=[task],
    )
 
def delete_task(parent: "KitsuProcessor", data):
    logging.info(f'delete_task: {data}')
    entity = {
        'id':  data['task_id'], 
        'type': 'Task',        
    }
    return ayon_api.post(
        f'{parent.entrypoint}/remove', 
        project_name="test_kitsu_project",
        entities=[entity],
    )
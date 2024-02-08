import httpx

from typing import Literal
from nxtools import logging

class KitsuResponse:
    """REST API Response."""

    def __init__(self, _data, _status_code:int = 200):
        self.status_code = _status_code
        self.data = _data
    
    def json(self):
        return self.data
  

class KitsuMock:

    # /api/data/projects
    api_data_projects = [
        {
            "name":"Kitsu Test Project",
            "code":"KTP",
            "description": None,
            "shotgun_id":None,
            "file_tree":None,
            "data":None,
            "has_avatar": False,
            "fps":"25",
            "ratio":"16:9",
            "resolution":"1920x1080",
            "production_type":"tvshow",
            "production_style":"3d",
            "start_date":"2024-01-01",
            "end_date":"2024-12-31",
            "man_days":None,
            "nb_episodes":0,
            "episode_span":0,
            "max_retakes":0,
            "is_clients_isolated": False,
            "is_preview_download_allowed":False,
            "homepage":"assets",
            "project_status_id":"project-status-id-1",
            "project_status_name":"Open",
            "default_preview_background_file_id":None,
            "id":"kitsu-project-id-1",
            "created_at":"2024-01-01T00:00:00",
            "updated_at":"2024-01-01T00:00:00",
            "type":"Project"
        },
        {
            "name":"Another Project",
            "code":"AP",
            "description":None,
            "shotgun_id":None,
            "file_tree":None,
            "data":None,
            "has_avatar": False,
            "fps":"25",
            "ratio":"16:9",
            "resolution":"1920x1080",
            "production_type":"tvshow",
            "production_style":"3d",
            "start_date":"2024-01-01",
            "end_date":"2024-12-31",
            "man_days":None,
            "nb_episodes":0,
            "episode_span":0,
            "max_retakes":0,
            "is_clients_isolated":False,
            "is_preview_download_allowed":False,
            "homepage":"assets",
            "project_status_id":"project-status-id-1",
            "project_status_name":"Open",
            "default_preview_background_file_id":None,
            "id":"kitsu-project-id-2",
            "created_at":"2024-01-01T00:00:00",
            "updated_at":"2024-01-01T00:00:00",
            "type":"Project"
        }
    ]
    api_data_task_types = [
        {
            "name": "Animation",
            "short_name": "ANIM",
            "color": "#DDD",
            "priority": 5,
            "for_entity": "Shot",
            "allow_timelog": True,
            "archived": False,
            "shotgun_id": None,
            "department_id": "dept-id-1",
            "id": "task-type-id-1",
            "created_at":"2024-01-01T00:00:00",
            "updated_at":"2024-01-01T00:00:00",
            "type": "TaskType"
        },
        {
            "name": "Compositing",
            "short_name": "COMP",
            "color": "#666",
            "priority": 5,
            "for_entity": "Shot",
            "allow_timelog": True,
            "archived": False,
            "shotgun_id": None,
            "department_id": "dept-id-1",
            "id": "task-type-id-2",
            "created_at":"2024-01-01T00:00:00",
            "updated_at":"2024-01-01T00:00:00",
            "type": "TaskType"
        }
    ]

    api_data_task_status = [
        {
            "name":"Todo",
            "archived":True,
            "short_name":"TODO",
            "color":"#f5f5f5",
            "priority":18,
            "is_done":False,
            "is_artist_allowed":True,
            "is_client_allowed":True,
            "is_retake":False,
            "is_feedback_request":False,
            "is_default":False,
            "shotgun_id": None,
            "for_concept":False,
            "id":"task-status-id-1",
            "created_at":"2024-01-01T00:00:00",
            "updated_at":"2024-01-01T00:00:00",
            "type":"TaskStatus"
        },
        {
            "name":"Approved",
            "archived":False,
            "short_name":"App",
            "color":"#22D160",
            "priority":1,
            "is_done":False,
            "is_artist_allowed":False,
            "is_client_allowed":False,
            "is_retake":False,
            "is_feedback_request":False,
            "is_default":False,
            "shotgun_id":None,
            "for_concept":True,
            "id":"task-status-id-2",
            "created_at":"2024-01-01T00:00:00",
            "updated_at":"2024-01-01T00:00:00",
            "type":"TaskStatus"
        }
    ]

 
    async def request(
        self,
        method: Literal["get", "post", "put", "delete", "patch"],
        endpoint: str,
        headers: dict[str, str] | None = None,
        **kwargs,
    ) -> httpx.Response:
        
        logging.info(f"kitsu_mock request [{method}] {endpoint}")
        


        if method == "get" and endpoint == "data/projects":
            return KitsuResponse(self.api_data_projects)
        
        if method == "get" and endpoint == "data/projects/kitsu-project-id-1":
            return KitsuResponse(self.api_data_projects[0])
        
        if method == "get" and endpoint == "data/projects/kitsu-project-id-2":
            return KitsuResponse(self.api_data_projects[1])
        
        if method == "get" and endpoint == "data/projects/kitsu-project-id-2/task-types":
            return KitsuResponse(self.api_data_task_types)
        
        if method == "get" and endpoint == "data/task-status":
            return KitsuResponse(self.api_data_task_status)
          
        
        raise Exception(f"Not mocked yet: [{method}] '{endpoint}' - {kwargs}")
        

    async def get(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("get", endpoint, **kwargs)

    async def post(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("post", endpoint, **kwargs)

    async def put(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("put", endpoint, **kwargs)

    async def delete(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("delete", endpoint, **kwargs)

    async def patch(self, endpoint: str, **kwargs) -> httpx.Response:
        return await self.request("patch", endpoint, **kwargs)


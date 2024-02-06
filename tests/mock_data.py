""" mock kitsu api data for patching gazu """

# /api/data/task-status
all_task_statuses = [
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

# /api/data/projects/{kitsu_project_id}/asset-types
all_asset_types_for_project = [
    {'name': 'Character', 'archived': False, 'id': 'asset-type-id-1'},
    {'name': 'Rig', 'archived': False, 'id': 'asset-type-id-2'},
    {'name': 'Location', 'archived': False, 'id': 'asset-type-id-3'},
]
# /api/data/projects/{kitsu_project_id}/task-types
all_task_types_for_project = [
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

# /api/data/projects/{kitsu_project_id}/episodes
all_episodes_for_project = [
  {
    "id": "episode-id-1",
    "name": "Episode 01",
    "code": "EP001",
    "description": "The first episode",
    "shotgun_id": None,
    "canceled": False,
    "nb_frames": None,
    "nb_entities_out": 0,
    "is_casting_standby": False,
    "status": "running",
    "project_id": "project-id-1",
    "entity_type_id": "entity-type-id-ep",
    "parent_id": None,
    "source_id": None,
    "preview_file_id": None,
    "data": {},
    "ready_for": None,
    "created_by": "user-id-1",
    "created_at":"2024-01-01T00:00:00",
    "updated_at":"2024-01-01T00:00:00",
    "type": "Episode"
  },
  {
    "id": "episode-id-2",
    "name": "Episode 02",
    "code": "EP002",
    "description": "The second episode",
    "shotgun_id": None,
    "canceled": False,
    "nb_frames": None,
    "nb_entities_out": 0,
    "is_casting_standby": False,
    "status": "running",
    "project_id": "project-id-1",
    "entity_type_id": "entity-type-id-ep",
    "parent_id": None,
    "source_id": None,
    "preview_file_id": None,
    "data": {},
    "ready_for": None,
    "created_by": "user-id-1",
    "created_at":"2024-01-01T00:00:00",
    "updated_at":"2024-01-01T00:00:00",
    "type": "Episode"
  }
]

# /api/data/projects/{kitsu_project_id}/sequences
all_sequences_for_project = [
  {
    "id": "sequence-id-1",
    "name": "SEQ01",
    "code": None,
    "description": "A Sequence",
    "shotgun_id": None,
    "canceled": False,
    "nb_frames": None,
    "nb_entities_out": 0,
    "is_casting_standby": False,
    "status": "running",
    "project_id": "project-id-1",
    "entity_type_id": "entity-type-id-seq",
    "parent_id": "episode-id-2",
    "source_id": None,
    "preview_file_id": None,
    "data": {},
    "ready_for": None,
    "created_by": "user-id-1",
    "created_at":"2024-01-01T00:00:00",
    "updated_at":"2024-01-01T00:00:00",
    "type": "Sequence"
  },
  {
    "id": "sequence-id-2",
    "name": "SEQ02",
    "code": None,
    "description": "Another Sequence",
    "shotgun_id": None,
    "canceled": False,
    "nb_frames": None,
    "nb_entities_out": 0,
    "is_casting_standby": False,
    "status": "running",
    "project_id": "project-id-1",
    "entity_type_id": "entity-type-id-seq",
    "parent_id": "episode-id-2",
    "source_id": None,
    "preview_file_id": None,
    "data": {},
    "ready_for": None,
    "created_by": "user-id-1",
    "created_at":"2024-01-01T00:00:00",
    "updated_at":"2024-01-01T00:00:00",
    "type": "Sequence"
  }
]

# /api/data/projects/{kitsu_project_id}/shots
all_shots_for_project = [
    {
        "id": "shot-id-1",
        "name": "SH001",
        "code": None,
        "description": "",
        "shotgun_id": None,
        "canceled": False,
        "nb_frames": None,
        "nb_entities_out": 0,
        "is_casting_standby": False,
        "status": "running",
        "project_id": "project-id-1",
        "entity_type_id": "entity-type-id-shot",
        "parent_id": "sequence-id-1",
        "source_id": None,
        "preview_file_id": "preview-id-1",
        "data": {
            "fps": "25",
            "frame_in": "0",
            "frame_out": "100"
        },
        "ready_for": None,
        "created_by": "user-id-1",
        "created_at":"2024-01-01T00:00:00",
        "updated_at":"2024-01-01T00:00:00",
        "type": "Shot"
    },
    {
        "id": "shot-id-2",
        "name": "SH002",
        "code": "sh2",
        "description": "description2",
        "shotgun_id": None,
        "canceled": False,
        "nb_frames": None,
        "nb_entities_out": 0,
        "is_casting_standby": False,
        "status": "running",
        "project_id": "project-id-1",
        "entity_type_id": "entity-type-id-shot",
        "parent_id": "sequence-id-1",
        "source_id": None,
        "preview_file_id": "preview-id-2",
        "data": {
            "fps": "25",
            "frame_in": "1",
            "frame_out": "150"
        },
        "ready_for": None,
        "created_by": "user-id-1",
        "created_at":"2024-01-01T00:00:00",
        "updated_at":"2024-01-01T00:00:00",
        "type": "Shot"
    },
    {
        "id": "shot-id-3",
        "name": "SH003",
        "code": None,
        "description": "",
        "shotgun_id": None,
        "canceled": False,
        "nb_frames": None,
        "nb_entities_out": 0,
        "is_casting_standby": False,
        "status": "running",
        "project_id": "project-id-1",
        "entity_type_id": "entity-type-id-shot",
        "parent_id": "sequence-id-2",
        "source_id": None,
        "preview_file_id": "preview-id-3",
        "data": {
            "fps": "29.97",
            "frame_in": "0",
            "frame_out": "50"
        },
        "ready_for": None,
        "created_by": "user-id-1",
        "created_at":"2024-01-01T00:00:00",
        "updated_at":"2024-01-01T00:00:00",
        "type": "Shot"
    }
]

# /api/data/projects/{kitsu_project_id}/assets
all_assets_for_project = [
  {
    "id": "asset-id-1",
    "name": "Main Character",
    "code": None,
    "description": "",
    "shotgun_id": None,
    "canceled": False,
    "nb_frames": None,
    "nb_entities_out": 0,
    "is_casting_standby": False,
    "status": "running",
    "project_id": "project-id-1",
    "entity_type_id": "asset-type-id-1",
    "parent_id": None,
    "source_id": None,
    "preview_file_id": None,
    "data": {},
    "ready_for": None,
    "created_by": "user-id-1",
    "created_at":"2024-01-01T00:00:00",
    "updated_at":"2024-01-01T00:00:00",
    "type": "Asset"
  },
  {
    "id": "asset-id-2",
    "name": "Second Character",
    "code": None,
    "description": "",
    "shotgun_id": None,
    "canceled": False,
    "nb_frames": None,
    "nb_entities_out": 0,
    "is_casting_standby": False,
    "status": "running",
    "project_id": "project-id-1",
    "entity_type_id": "asset-type-id-2",
    "parent_id": None,
    "source_id": None,
    "preview_file_id": None,
    "data": {},
    "ready_for": None,
    "created_by": "user-id-1",
    "created_at":"2024-01-01T00:00:00",
    "updated_at":"2024-01-01T00:00:00",
    "type": "Asset"
  }
]

# adds the preprocessing that fullsync does
all_assets_for_project_preprocessed = [
    { **all_assets_for_project[0], 'asset_type_name': "Character"},
    { **all_assets_for_project[1], 'asset_type_name': "Rig"},
]


all_tasks_for_project = [
    {
        
        "id": "task-id-1",
        "name": "main",
        "description": None,
        "priority": 0,
        "duration": 0,
        "estimation": 0,
        "completion_rate": 0,
        "retake_count": 0,
        "sort_order": 0,
        "start_date": None,
        "due_date": None,
        "real_start_date": None,
        "end_date": None,
        "last_comment_date": "2024-01-01T00:00:00",
        "nb_assets_ready": 0,
        "data": None,
        "shotgun_id": None,
        "assignees": [
            "user-id-1",
            "user-id-3",
        ],
        "project_id": "project-id-1",
        "task_type_id": "task-type-id-1",
        "task_status_id": "task-status-id-2",
        "entity_id": "shot-id-1",
        "assigner_id": "user-id-1",
        "created_at":"2024-01-01T00:00:00",
        "updated_at":"2024-01-01T00:00:00",
        "type": "Task"
    },
    {
        
        "id": "task-id-2",
        "name": "main",
        "description": None,
        "priority": 0,
        "duration": 0,
        "estimation": 0,
        "completion_rate": 0,
        "retake_count": 0,
        "sort_order": 0,
        "start_date": None,
        "due_date": None,
        "real_start_date": None,
        "end_date": None,
        "last_comment_date": "2024-01-01T00:00:00",
        "nb_assets_ready": 0,
        "data": None,
        "shotgun_id": None,
        "assignees": [],
        "project_id": "project-id-1",
        "task_type_id": "task-type-id-2",
        "task_status_id": "task-status-id-1",
        "entity_id": "shot-id-1",
        "assigner_id": "user-id-1",
        "created_at":"2024-01-01T00:00:00",
        "updated_at":"2024-01-01T00:00:00",
        "type": "Task"
    }
]

# adds the preprocessing that fullsync does
all_tasks_for_project_preprocessed = [
    { **all_tasks_for_project[0], 'name': 'animation', 'task_type_name': "Animation", 'task_status_name': "Todo"},
    { **all_tasks_for_project[1], 'name': 'compositing', 'task_type_name': "Compositing", 'task_status_name': "Approved"},
]
 
    
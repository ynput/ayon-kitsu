DEFAULT_VALUES = {
    "entities_naming_pattern": {
        "episode": "E##",
        "sequence": "SQ##",
        "shot": "SH##",
    },
    "publish": {
        "IntegrateKitsuNote": {
            "set_status_note": False,
            "note_status_shortname": "wfa",
            "status_change_conditions": {
                "status_conditions": [],
                "product_type_requirements": [],
            },
            "custom_comment_template": {
                "enabled": False,
                "comment_template": """{comment}

|  |  |
|--|--|
| version | `{version}` |
| family | `{family}` |
| name | `{name}` |""",
            },
        }
    },
    "sync_settings": {
        "delete_projects": False,
        "sync_users": {
            "enabled": False,
            "default_password": "default_password",
            "access_group": "kitsu_group",
        },
        "default_sync_info": {
            "default_task_info": [
                {
                    "name": "Concept",
                    "short_name": "cncp",
                    "icon": "lightbulb",
                },
                {
                    "name": "Modeling",
                    "short_name": "mdl",
                    "icon": "language",
                },
                {
                    "name": "Shading",
                    "short_name": "shdn",
                    "icon": "format_paint",
                },
                {
                    "name": "Rigging",
                    "short_name": "rig",
                    "icon": "construction",
                },
                {
                    "name": "Edit",
                    "short_name": "edit",
                    "icon": "cut",
                },
                {
                    "name": "Storyboard",
                    "short_name": "stry",
                    "icon": "image",
                },
                {
                    "name": "Layout",
                    "short_name": "lay",
                    "icon": "nature_people",
                },
                {
                    "name": "Animation",
                    "short_name": "anim",
                    "icon": "directions_run",
                },
                {
                    "name": "Lighting",
                    "short_name": "lgt",
                    "icon": "highlight",
                },
                {
                    "name": "FX",
                    "short_name": "fx",
                    "icon": "local_fire_department",
                },
                {
                    "name": "Compositing",
                    "short_name": "comp",
                    "icon": "layers",
                },
                {
                    "name": "Recording",
                    "short_name": "rcrd",
                    "icon": "video_camera_back",
                },
            ],
            "default_status_info": [
                {
                    "short_name": "todo",
                    "state": "not_started",
                    "icon": "fiber_new",
                },
                {
                    "short_name": "neutral",
                    "state": "in_progress",
                    "icon": "timer",
                },
                {
                    "short_name": "wip",
                    "state": "in_progress",
                    "icon": "play_arrow",
                },
                {
                    "short_name": "wfa",
                    "state": "in_progress",
                    "icon": "visibility",
                },
                {
                    "short_name": "retake",
                    "state": "in_progress",
                    "icon": "timer",
                },
                {
                    "short_name": "done",
                    "state": "done",
                    "icon": "task_alt",
                },
                {
                    "short_name": "ready",
                    "state": "not_started",
                    "icon": "timer",
                },
                {
                    "short_name": "approved",
                    "state": "done",
                    "icon": "task_alt",
                },
                {
                    "short_name": "rejected",
                    "state": "blocked",
                    "icon": "block",
                },
            ],
        },
    },
}

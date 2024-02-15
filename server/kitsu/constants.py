# This file contains constants that could later be
# moved to Ayons settings.
# But for now they live here.

# Default password for newly created users
CONSTANT_KITSU_USER_PASSWORD = "default_password"

# The default kitsu access group name
CONSTANT_KITSU_ACCESS_GROUP_NAME = "kitsu_group"

# The default kitsu access group name
# Kitsu roles:
# Studio manager = admin
# Vendor = vendor
# Client = client
# Production manager = manager
# Supervisor = supervisor
# Artist = user
CONSTANT_KITSU_ROLES = {
    "admin": {
        "data": {
            "defaultAccessGroups": [CONSTANT_KITSU_ACCESS_GROUP_NAME],
        },
        "isAdmin": True,
    },
    "vendor": {
        "data": {
            "defaultAccessGroups": [CONSTANT_KITSU_ACCESS_GROUP_NAME],
        },
    },
    "client": {
        "data": {
            "defaultAccessGroups": [CONSTANT_KITSU_ACCESS_GROUP_NAME],
        },
        "isGuest": True,
    },
    "manager": {
        "data": {
            "defaultAccessGroups": [CONSTANT_KITSU_ACCESS_GROUP_NAME],
        },
        "isManager": True,
    },
    "supervisor": {
        "data": {
            "defaultAccessGroups": [CONSTANT_KITSU_ACCESS_GROUP_NAME],
        },
        "isManager": True,
    },
    "user": {
        "data": {
            "defaultAccessGroups": [CONSTANT_KITSU_ACCESS_GROUP_NAME],
        },
    },
}

# Add Kitsu models that Ayon doesn't have by default.
CONSTANT_KITSU_MODELS: dict[str, dict[str, str]] = {
    "Edit": {
        "shortName": "ed",
        "icon": "cut",
    },
    "Concept": {
        "shortName": "co",
        "icon": "image",
    },
}

# Manualy set the icon (and Short Name in the future) for non ayon default task types
CONSTANT_KITSU_TASKS: dict[str, dict[str, str]] = {
    "concept": {
        "icon": "lightbulb",
    },
    "shading": {
        "icon": "format_paint",
    },
    "recording": {
        "icon": "video_camera_back",
    },
}

# Manualy set the data for the default kitsu task statuses
CONSTANT_KITSU_STATUSES: dict[str, dict[str, str]] = {
    "todo": {
        "icon": "fiber_new",
        "state": "not_started",
    },
    "neutral": {
        "icon": "timer",
        "state": "in_progress",
    },
    "wip": {
        "icon": "play_arrow",
        "state": "in_progress",
    },
    "wfa": {
        "icon": "visibility",
        "state": "in_progress",
    },
    "retake": {
        "icon": "timer",
        "state": "in_progress",
    },
    "done": {
        "icon": "task_alt",
        "state": "done",
    },
    "ready": {
        "icon": "timer",
        "state": "not_started",
    },
    "approved": {
        "icon": "task_alt",
        "state": "done",
    },
    "rejected": {
        "icon": "block",
        "state": "blocked",
    },
}

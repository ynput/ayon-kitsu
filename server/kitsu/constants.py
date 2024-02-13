# This file contains constants that could later be
# moved to Ayons settings.
# But for now they live here.

# Add Kitsu models that Ayon doesn't have by default.
constant_kitsu_models: dict[str, dict[str, str]] = {
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
constant_kitsu_tasks: dict[str, dict[str, str]] = {
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
constant_kitsu_statuses: dict[str, dict[str, str]] = {
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

# Add Kitsu models that Ayon doesn't have by default.
kitsu_models: list[dict[str, str]] = [
    {
        "name": "Edits",
        "shortName": "ed",
        "icon": "cut",
    },
]

# Manualy set the icon for non ayon default task types
kitsu_tasks: dict[str, dict[str, str]] = {
    "concept": {
        "icon": "lightbulb",
    },
    "shading": {
        "icon": "format_paint",
    },
}

# Manualy set the data for the default kitsu task statuses
kitsu_statuses: dict[str, dict[str, str]] = {
    "todo": {
        "icon": "fiber_new",
        "state": "not_started",
    },
    "neutral": {
        "icon": "",
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

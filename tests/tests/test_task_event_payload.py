"""Task event payload regression tests without a live AYON server."""

from unittest.mock import Mock

import pytest
from processor import update_from_kitsu


@pytest.mark.parametrize(
    "project_payload",
    [{}, {"project_id": None}, {"project_id": ""}, {"project_id": "project"}],
    ids=["missing", "null", "empty", "present"],
)
@pytest.mark.parametrize("paired", [True, False], ids=["paired", "unpaired"])
@pytest.mark.parametrize(
    "assignees",
    [["person", "unknown-person"], []],
    ids=["assigned", "cleared"],
)
def test_task_event_project_id(
    monkeypatch, project_payload, paired, assignees
):
    """Resolve legacy payloads while preserving task assignment sync."""
    parent = Mock(entrypoint="/addons/kitsu/test")
    parent.get_paired_ayon_project.return_value = (
        "ayon-project" if paired else None
    )
    task = {
        "id": "task",
        "project_id": "project",
        "name": "main",
        "task_type_id": "animation",
        "task_status_id": "approved",
        "assignees": assignees,
    }
    get_task = Mock(return_value=task)
    get_persons = Mock(
        return_value=[{"id": "person", "email": "artist@example.com"}]
    )
    get_types = Mock(return_value=[{"id": "animation", "name": "Animation"}])
    get_statuses = Mock(return_value=[{"id": "approved", "name": "Approved"}])
    get_users = Mock(
        return_value=[
            {"name": "artist", "attrib": {"email": "artist@example.com"}}
        ]
    )
    post = Mock()
    monkeypatch.setattr(update_from_kitsu.gazu.task, "get_task", get_task)
    monkeypatch.setattr(
        update_from_kitsu.gazu.person, "all_persons", get_persons
    )
    monkeypatch.setattr(
        update_from_kitsu.gazu.task, "all_task_types_for_project", get_types
    )
    monkeypatch.setattr(
        update_from_kitsu.gazu.task, "all_task_statuses", get_statuses
    )
    monkeypatch.setattr(update_from_kitsu.ayon_api, "get_users", get_users)
    monkeypatch.setattr(
        update_from_kitsu.ayon_api, "get_base_url", lambda: "https://ayon.test"
    )
    monkeypatch.setattr(update_from_kitsu.ayon_api, "post", post)

    result = update_from_kitsu.create_or_update_task(
        parent, {"task_id": "task", **project_payload}
    )

    parent.get_paired_ayon_project.assert_called_once_with("project")
    if paired or not project_payload.get("project_id"):
        get_task.assert_called_once_with("task")
    else:
        get_task.assert_not_called()

    if not paired:
        assert result is None
        for call in (get_persons, get_types, get_statuses, get_users, post):
            call.assert_not_called()
        return

    assert result is post.return_value
    post.assert_called_once_with(
        "/addons/kitsu/test/push",
        project_name="ayon-project",
        entities=[
            {
                **task,
                "name": "animation",
                "task_type_name": "Animation",
                "task_status_name": "Approved",
                "assignees": ["artist"] if assignees else [],
                "ayon_server_url": "https://ayon.test",
            }
        ],
    )

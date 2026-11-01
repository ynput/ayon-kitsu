"""Unit tests for IdentityResolver (Task 8.5).

Validates: Requirements 3.1 to 3.9, 4.10.
"""

from unittest.mock import MagicMock
import pytest

from processor.outbound.constants import (
    ERROR_NOT_FOUND,
    ERROR_UNREACHABLE,
)
from processor.outbound.identity import IdentityResolver
from processor.outbound.kitsu_writer import KitsuWriterError

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


class FakeAyonClient:
    """Mock AYON client for testing IdentityResolver."""

    def __init__(self):
        self.entities = {}
        self.owners_response = {"folders": [], "tasks": [], "users": []}

    def get_task_by_id(self, project_name, task_id):
        return self.entities.get(("task", task_id))

    def get_folder_by_id(self, project_name, folder_id):
        return self.entities.get(("folder", folder_id))

    def get_user(self, user_id):
        return self.entities.get(("user", user_id))

    def get(self, url):
        res = MagicMock()
        res.data = self.owners_response
        return res


def test_identity_entity_gone():
    """Missing AYON entity skips with entity no longer exists."""
    ayon_client = FakeAyonClient()
    writer = MagicMock()
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-gone",
        expected_kind="task",
    )
    assert res["ok"] is False
    assert res["outcome"] == "skip"
    assert "AYON entity task-gone no longer exists" in res["reason"]
    assert res["retryable"] is False
    # No Kitsu call is made
    writer.get_task.assert_not_called()


def test_identity_missing_kitsu_id():
    """AYON entity with missing kitsuId skips with no kitsu id reason."""
    ayon_client = FakeAyonClient()
    ayon_client.entities[("task", "task-1")] = {
        "id": "task-1",
        "name": "Animation",
        "data": {},
    }
    writer = MagicMock()
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-1",
        expected_kind="task",
    )
    assert res["ok"] is False
    assert res["outcome"] == "skip"
    assert "has no Kitsu id" in res["reason"]
    writer.get_task.assert_not_called()


def test_identity_structural_folder():
    """Structural folder skips with structural folder reason."""
    ayon_client = FakeAyonClient()
    ayon_client.entities[("folder", "fold-1")] = {
        "id": "fold-1",
        "name": "Shots",
        "data": {"kitsuId": "shot"},
    }
    writer = MagicMock()
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="folder",
        entity_id="fold-1",
        expected_kind="folder",
    )
    assert res["ok"] is False
    assert res["outcome"] == "skip"
    assert "structural folder" in res["reason"]
    writer.get_entity.assert_not_called()


def test_identity_duplicate_owners():
    """Duplicate owners fails with duplicate owners reason."""
    ayon_client = FakeAyonClient()
    ayon_client.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kit-dup-1"},
    }
    ayon_client.owners_response = {
        "folders": [],
        "tasks": ["task-1", "task-2"],
        "users": [],
    }
    writer = MagicMock()
    writer.get_task.return_value = {
        "id": "kit-dup-1",
        "type": "Task",
        "project_id": "p-1",
    }
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-1",
        expected_kind="task",
        kitsu_project_id="p-1",
    )
    assert res["ok"] is False
    assert res["outcome"] == "fail"
    assert res["error"] == "owners"
    assert "carried by 2 AYON entities" in res["reason"]
    assert "task-1" in res["reason"]
    assert "task-2" in res["reason"]


def test_identity_wrong_kind():
    """Kind mismatch between AYON and Kitsu fails with kind_mismatch."""
    ayon_client = FakeAyonClient()
    ayon_client.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kit-asset-1"},
    }
    ayon_client.owners_response = {
        "folders": [],
        "tasks": ["task-1"],
        "users": [],
    }
    writer = MagicMock()
    # Task points to an Asset
    writer.get_task.return_value = {
        "id": "kit-asset-1",
        "type": "Asset",
        "project_id": "p-1",
    }
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-1",
        expected_kind="task",
        kitsu_project_id="p-1",
    )
    assert res["ok"] is False
    assert res["outcome"] == "fail"
    assert res["error"] == "kind_mismatch"
    assert "does not match AYON" in res["reason"]


def test_identity_wrong_project():
    """Project mismatch between paired project and Kitsu fails."""
    ayon_client = FakeAyonClient()
    ayon_client.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kit-task-1"},
    }
    ayon_client.owners_response = {
        "folders": [],
        "tasks": ["task-1"],
        "users": [],
    }
    writer = MagicMock()
    writer.get_task.return_value = {
        "id": "kit-task-1",
        "type": "Task",
        "project_id": "wrong-proj",
    }
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-1",
        expected_kind="task",
        kitsu_project_id="correct-proj",
    )
    assert res["ok"] is False
    assert res["outcome"] == "fail"
    assert res["error"] == "project_mismatch"
    assert "correct-proj" in res["reason"]
    assert "wrong-proj" in res["reason"]


def test_identity_kitsu_404():
    """Kitsu 404 fails and states entity does not exist in Kitsu."""
    ayon_client = FakeAyonClient()
    ayon_client.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kit-missing"},
    }
    writer = MagicMock()
    writer.get_task.side_effect = KitsuWriterError(
        ERROR_NOT_FOUND, "Not found", http_status=404, retryable=False
    )
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-1",
        expected_kind="task",
    )
    assert res["ok"] is False
    assert res["outcome"] == "fail"
    assert "does not exist in Kitsu" in res["reason"]
    assert res["retryable"] is False


def test_identity_kitsu_unreachable():
    """Unreachable during resolution fails with retryable and not missing."""
    ayon_client = FakeAyonClient()
    ayon_client.entities[("task", "task-1")] = {
        "id": "task-1",
        "data": {"kitsuId": "kit-task-1"},
    }
    writer = MagicMock()
    writer.get_task.side_effect = KitsuWriterError(
        ERROR_UNREACHABLE, "Connection refused", retryable=True
    )
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-1",
        expected_kind="task",
    )
    assert res["ok"] is False
    assert res["outcome"] == "fail"
    assert "identity resolution could not complete" in res["reason"]
    assert "does not exist in Kitsu" not in res["reason"]
    assert res["retryable"] is True


def test_identity_success():
    """Valid entity resolves successfully and returns ayon and kitsu data."""
    ayon_client = FakeAyonClient()
    task_entity = {
        "id": "task-1",
        "name": "Anim",
        "data": {"kitsuId": "kit-1"},
    }
    ayon_client.entities[("task", "task-1")] = task_entity
    ayon_client.owners_response = {
        "folders": [],
        "tasks": ["task-1"],
        "users": [],
    }
    kitsu_task = {
        "id": "kit-1",
        "type": "Task",
        "project_id": "p-1",
    }
    writer = MagicMock()
    writer.get_task.return_value = kitsu_task
    resolver = IdentityResolver(ayon_client, writer)

    res = resolver.resolve(
        project_name="proj",
        entity_type="task",
        entity_id="task-1",
        expected_kind="task",
        kitsu_project_id="p-1",
    )
    assert res["ok"] is True
    assert res["ayon"] == task_entity
    assert res["kitsu"] == kitsu_task

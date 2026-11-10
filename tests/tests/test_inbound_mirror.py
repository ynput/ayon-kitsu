"""Pinned tests for match_assignees_by_email (Task 16.4).

Validates that the pure email matching logic preserves 100% of the
pre-refactor behavior from ``processor/utils.preprocess_task``,
including duplicate email "last user wins" semantics and case sensitivity.

Validates: Requirements 2.5, 7.2, 7.5, 14.8.
"""

from unittest.mock import MagicMock, patch
import pytest

from processor.outbound.inbound_mirror import match_assignees_by_email
from processor.utils import preprocess_task

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def test_match_assignees_nominal():
    """Nominal email matching resolves Kitsu emails to AYON usernames."""
    ayon_users = [
        {"name": "alice", "attrib": {"email": "alice@example.com"}},
        {"name": "bob", "attrib": {"email": "bob@example.com"}},
        {"name": "charlie", "attrib": {"email": "charlie@example.com"}},
    ]
    person_emails = ["alice@example.com", "bob@example.com"]
    result = match_assignees_by_email(person_emails, ayon_users)
    assert set(result) == {"alice", "bob"}


def test_match_assignees_duplicate_email_last_user_wins():
    """Duplicate emails in AYON exhibit 'last user wins' semantics (F13)."""
    ayon_users = [
        {"name": "first_user", "attrib": {"email": "shared@example.com"}},
        {"name": "last_user", "attrib": {"email": "shared@example.com"}},
    ]
    result = match_assignees_by_email(["shared@example.com"], ayon_users)
    assert result == ["last_user"]


def test_match_assignees_case_sensitive():
    """Email comparison is exact and case-sensitive."""
    ayon_users = [
        {"name": "alice", "attrib": {"email": "alice@example.com"}},
    ]
    # Differing case produces no match
    assert match_assignees_by_email(["Alice@example.com"], ayon_users) == []
    assert match_assignees_by_email(["ALICE@EXAMPLE.COM"], ayon_users) == []


def test_match_assignees_unmatched_silently_dropped():
    """Unmatched emails or persons without emails are silently omitted."""
    ayon_users = [
        {"name": "alice", "attrib": {"email": "alice@example.com"}},
    ]
    person_emails = ["alice@example.com", "unknown@example.com", "", None]
    result = match_assignees_by_email(person_emails, ayon_users)
    assert result == ["alice"]


def test_match_assignees_empty_inputs():
    """Empty person emails or user lists produce an empty result list."""
    assert match_assignees_by_email([], [{"name": "alice"}]) == []
    assert match_assignees_by_email(["alice@example.com"], []) == []
    assert match_assignees_by_email([], []) == []


def test_preprocess_task_delegates_to_match_assignees():
    """utils.preprocess_task populates task['assignees'] via pure matcher."""
    ayon_users = [
        {"name": "alice", "attrib": {"email": "alice@example.com"}},
        {"name": "bob", "attrib": {"email": "bob@example.com"}},
    ]
    task = {
        "name": "anim",
        "persons": [
            {"email": "alice@example.com"},
            {"email": "stranger@example.com"},
        ],
    }

    with patch("processor.utils.ayon_api.get_users", return_value=ayon_users):
        processed = preprocess_task(
            kitsu_project_id="proj-1",
            task=task,
            task_types={"tt-1": "Animation"},
            statuses={"st-1": "Approved"},
        )

    assert processed["assignees"] == ["alice"]

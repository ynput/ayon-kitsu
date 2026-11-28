"""Unit tests for describe.py.

Validates: Requirements 1.5, 6.4, 6.9, 13.1, 13.2, 13.3, 13.6.
"""

import pytest

from processor.outbound.constants import (
    CONFLICT_POLICY_AYON_WINS,
    CONFLICT_POLICY_KITSU_WINS,
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    DECISION_SKIPPED,
)
from processor.outbound.describe import (
    build_log_line,
    describe_job,
    latency_summary,
    log_level_for_decision,
    log_line,
    redact,
    status_comment_text,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


# ---------------------------------------------------------------------------
# status_comment_text (Requirements 6.4, 6.9)
# ---------------------------------------------------------------------------


def test_status_comment_text_with_user():
    """Comment text embeds username and status name in quotes."""
    res = status_comment_text("In Progress", "alice")
    assert res == "[AYON] Status set to 'In Progress' by alice."


def test_status_comment_text_without_user():
    """Comment text falls back to no-known-user variant when user is absent."""
    expected = (
        "[AYON] Status set to 'Approved' in AYON with no known user."
    )
    res = status_comment_text("Approved", None)
    assert res == expected

    res2 = status_comment_text("Approved", "")
    assert res2 == expected


# ---------------------------------------------------------------------------
# redact (Requirement 13.6)
# ---------------------------------------------------------------------------


def test_redact_secrets():
    """Secrets are replaced with non-colliding placeholder."""
    text = "Connecting with user admin and secret_token_xyz to kitsu.com"
    secrets = ["secret_token_xyz", "admin"]
    res = redact(text, secrets)
    assert "admin" not in res
    assert "secret_token_xyz" not in res
    assert "[REDACTED]" in res


def test_redact_handles_empty_and_overlapping():
    """Empty secrets and overlapping secrets are handled safely."""
    text = "apikey123 and apikey12345"
    secrets = ["apikey123", "apikey12345", ""]
    res = redact(text, secrets)
    assert "apikey123" not in res
    assert "apikey12345" not in res


# ---------------------------------------------------------------------------
# latency_summary (Requirement 1.5)
# ---------------------------------------------------------------------------


def test_latency_summary_empty():
    """Empty sample list returns None metrics and count 0."""
    res = latency_summary([], timeouts=2)
    assert res["count"] == 0
    assert res["min"] is None
    assert res["median"] is None
    assert res["p95"] is None
    assert res["max"] is None
    assert res["timeouts"] == 2


def test_latency_summary_known_samples():
    """Latency summary calculates min, median, p95 and max correctly."""
    # 100 samples: 1.0 to 100.0
    samples = [float(i) for i in range(1, 101)]
    res = latency_summary(samples, timeouts=0)
    assert res["count"] == 100
    assert res["min"] == 1.0
    assert res["max"] == 100.0
    assert res["median"] == 50.5
    # rank 99 * 0.95 = 94.05 -> index 94 (95.0) + 0.05 * 1.0 = 95.05
    assert abs(res["p95"] - 95.05) < 1e-4
    assert res["timeouts"] == 0


# ---------------------------------------------------------------------------
# build_log_line (Requirement 13.1)
# ---------------------------------------------------------------------------


def test_build_log_line_levels():
    """Log level matches decision."""
    assert log_level_for_decision(DECISION_APPLIED) == "INFO"
    assert log_level_for_decision(DECISION_SKIPPED) == "INFO"
    assert log_level_for_decision(DECISION_CONFLICT) == "WARNING"
    assert log_level_for_decision(DECISION_FAILED) == "ERROR"


def test_build_log_line_content():
    """Log line contains decision, project, entity, kitsu_id, category."""
    details = {
        "project_name": "test_project",
        "entity_id": "ent-123",
        "kitsu_id": "kit-456",
        "category": "task_status",
        "job_id": "job-789",
    }
    level, msg = build_log_line(DECISION_APPLIED, details)
    assert level == "INFO"
    assert "applied" in msg
    assert "test_project" in msg
    assert "ent-123" in msg
    assert "kit-456" in msg
    assert "task_status" in msg
    assert "job-789" in msg

    # Alias check
    l2, m2 = log_line(DECISION_APPLIED, details)
    assert (l2, m2) == (level, msg)


# ---------------------------------------------------------------------------
# describe_job (Requirements 4.3, 4.4, 9.4, 9.5, 10.1, 10.6, 13.2, 13.3)
# ---------------------------------------------------------------------------


def test_describe_job_applied():
    """Applied description starts with Applied: and lists values."""
    details = {
        "kitsu_entity_type": "Task",
        "kitsu_id": "kit-task-1",
        "writes": [
            {
                "field": "task_status_id",
                "before": "stat-old",
                "sent": "stat-new",
            }
        ],
    }
    res = describe_job(DECISION_APPLIED, details)
    assert res.startswith("Applied:")
    assert "Task kit-task-1" in res
    assert "task_status_id" in res
    assert "before: stat-old" in res
    assert "sent: stat-new" in res


def test_describe_job_applied_assignees_sorting():
    """Assignees in applied descriptions are sorted by person name."""
    details = {
        "kitsu_entity_type": "Task",
        "kitsu_id": "k1",
        "writes": [
            {
                "field": "assignees",
                "before": [{"name": "Charlie"}, {"name": "Alice"}],
                "sent": [{"name": "Bob"}, {"name": "Alice"}],
            }
        ],
    }
    res = describe_job(DECISION_APPLIED, details)
    assert "before: [Alice, Charlie]" in res
    assert "sent: [Alice, Bob]" in res


def test_describe_job_skipped_gated():
    """Gated skip contains event, project, category and no-write clause."""
    details = {
        "reason": "task_status disabled at event creation time",
        "event_id": "ev-999",
        "project_name": "my_proj",
        "category": "task_status",
    }
    res = describe_job(DECISION_SKIPPED, details)
    assert res.startswith("Skipped:")
    assert "ev-999" in res
    assert "my_proj" in res
    assert "task_status" in res
    assert "no kitsu field was written" in res.lower()


def test_describe_job_conflict_kitsu_wins():
    """Conflict under kitsu_wins records values and no-write clause."""
    details = {
        "field": "task_status_id",
        "previous": "stat-1",
        "kitsu_current": "stat-2",
        "new": "stat-3",
        "policy": CONFLICT_POLICY_KITSU_WINS,
    }
    res = describe_job(DECISION_CONFLICT, details)
    assert res.startswith("Conflict:")
    assert "previous AYON: stat-1" in res
    assert "current Kitsu: stat-2" in res
    assert "rejected AYON: stat-3" in res
    assert "no kitsu field was written" in res.lower()


def test_describe_job_conflict_ayon_wins():
    """Conflict under ayon_wins records overwritten and written values."""
    details = {
        "field": "task_status_id",
        "overwritten": "stat-2",
        "written": "stat-3",
        "policy": CONFLICT_POLICY_AYON_WINS,
    }
    res = describe_job(DECISION_CONFLICT, details)
    assert res.startswith("Conflict:")
    assert "overwritten Kitsu: stat-2" in res
    assert "written AYON: stat-3" in res
    assert "no kitsu field was written" not in res.lower()


def test_describe_job_failed_retryable():
    """Retryable failure contains attempt, error and no-write clause."""
    details = {
        "retryable": True,
        "attempt": 1,
        "error_kind": "unreachable",
    }
    res = describe_job(DECISION_FAILED, details)
    assert res.startswith("Failed:")
    assert "attempt 1/4" in res
    assert "Kitsu unreachable" in res
    assert "no kitsu field was written" in res.lower()

    details_500 = {
        "retryable": True,
        "attempt": 2,
        "error_kind": "server_error",
        "http_status": 503,
    }
    res_500 = describe_job(DECISION_FAILED, details_500)
    assert "attempt 2/4" in res_500
    assert "Kitsu HTTP 503" in res_500
    assert "no kitsu field was written" in res_500.lower()


def test_describe_job_failed_final():
    """Final failure contains entity, category, unwritten and no write."""
    details = {
        "retryable": False,
        "entity_id": "ent-1",
        "kitsu_id": "kit-1",
        "category": "task_status",
        "unwritten": {"task_status_id": "Approved"},
    }
    res = describe_job(DECISION_FAILED, details)
    assert res.startswith("Failed:")
    assert "entity ent-1" in res
    assert "kitsu_id kit-1" in res
    assert "category task_status" in res
    assert "task_status_id=Approved" in res
    assert "no kitsu field was written" in res.lower()

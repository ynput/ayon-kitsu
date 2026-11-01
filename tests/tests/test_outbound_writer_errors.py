"""Unit tests for KitsuWriter and error classification (Task 8.3).

Validates: Requirements 6.1, 6.4, 6.8, 10.1, 10.3, 10.4, 13.6.
"""

from unittest.mock import MagicMock
import pytest
import requests

import gazu.exception
from processor.outbound.constants import (
    ERROR_NOT_FOUND,
    ERROR_PERMISSION,
    ERROR_REJECTED,
    ERROR_SERVER_ERROR,
    ERROR_UNREACHABLE,
)
from processor.outbound.kitsu_writer import (
    KitsuWriter,
    classify_kitsu_error,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def _mock_http_error(status_code: int) -> requests.exceptions.HTTPError:
    """Create a mock requests.HTTPError with a response status code."""
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(
        f"HTTP {status_code} Error", response=response
    )


def test_classify_connection_refused_and_dns():
    """Connection refused and DNS resolution errors classify as unreachable."""
    refused = requests.exceptions.ConnectionError("Connection refused")
    err1 = classify_kitsu_error(refused)
    assert err1.kind == ERROR_UNREACHABLE
    assert err1.retryable is True
    assert err1.http_status is None

    dns = requests.exceptions.ConnectionError(
        "Failed to resolve 'kitsu.local' (getaddrinfo failed)"
    )
    err2 = classify_kitsu_error(dns)
    assert err2.kind == ERROR_UNREACHABLE
    assert err2.retryable is True


def test_classify_timeout():
    """Timeout exceptions classify as unreachable and retryable."""
    timeout_exc = requests.exceptions.Timeout(
        "Read timed out after 30 seconds"
    )
    err = classify_kitsu_error(timeout_exc)
    assert err.kind == ERROR_UNREACHABLE
    assert err.retryable is True


def test_classify_server_errors_500_to_599():
    """500-599 errors classify as server_error and retryable with status."""
    gazu_500 = gazu.exception.ServerErrorException("Server error")
    err1 = classify_kitsu_error(gazu_500)
    assert err1.kind == ERROR_SERVER_ERROR
    assert err1.retryable is True
    assert err1.http_status == 500

    for code in (500, 502, 503, 504):
        http_err = _mock_http_error(code)
        err = classify_kitsu_error(http_err)
        assert err.kind == ERROR_SERVER_ERROR
        assert err.retryable is True
        assert err.http_status == code


def test_classify_permission_errors_401_403():
    """401 and 403 classify as permission error and final."""
    not_auth = gazu.exception.NotAuthenticatedException("Not logged in")
    err1 = classify_kitsu_error(not_auth)
    assert err1.kind == ERROR_PERMISSION
    assert err1.retryable is False
    assert err1.http_status == 401

    not_allowed = gazu.exception.NotAllowedException("Forbidden")
    err2 = classify_kitsu_error(not_allowed)
    assert err2.kind == ERROR_PERMISSION
    assert err2.retryable is False
    assert err2.http_status == 403

    auth_failed = gazu.exception.AuthFailedException("Bad password")
    err3 = classify_kitsu_error(auth_failed)
    assert err3.kind == ERROR_PERMISSION
    assert err3.retryable is False


def test_classify_not_found_404():
    """404 classifies as not_found and final."""
    route_not_found = gazu.exception.RouteNotFoundException("Route not found")
    err1 = classify_kitsu_error(route_not_found)
    assert err1.kind == ERROR_NOT_FOUND
    assert err1.retryable is False
    assert err1.http_status == 404

    http_404 = _mock_http_error(404)
    err2 = classify_kitsu_error(http_404)
    assert err2.kind == ERROR_NOT_FOUND
    assert err2.retryable is False
    assert err2.http_status == 404


def test_classify_rejected_other_4xx():
    """Other 4xx classify as rejected and final."""
    param_exc = gazu.exception.ParameterException("path", "Bad parameter")
    err1 = classify_kitsu_error(param_exc)
    assert err1.kind == ERROR_REJECTED
    assert err1.retryable is False
    assert err1.http_status == 400

    val_cls = getattr(gazu.exception, "ValidationException", None)
    if val_cls is not None:
        val_exc = val_cls("path", "Invalid data")
        err2 = classify_kitsu_error(val_exc)
        assert err2.kind == ERROR_REJECTED
        assert err2.retryable is False
        assert err2.http_status == 422
    else:

        class MockValidationException(Exception):
            pass

        err_mock = classify_kitsu_error(MockValidationException("msg"))
        assert err_mock is not None

    for code in (400, 405, 409, 422):
        http_err = _mock_http_error(code)
        err = classify_kitsu_error(http_err)
        assert err.kind == ERROR_REJECTED
        assert err.retryable is False
        assert err.http_status == code


def test_classify_redacts_secrets():
    """Secrets passed to classify_kitsu_error are redacted from the message."""
    secret_pass = "super_secret_token_123"
    exc = Exception(f"Failed with key {secret_pass} on kitsu")
    err = classify_kitsu_error(exc, secrets=[secret_pass])
    assert secret_pass not in err.message
    assert "[REDACTED]" in err.message


def test_writer_task_statuses_caching():
    """task_statuses caches results for 60s using injected clock."""
    fake_client = MagicMock()
    mock_statuses = [{"id": "s1", "name": "Approved"}]

    current_time = 1000.0

    def fake_clock():
        return current_time

    writer = KitsuWriter(client=fake_client, clock=fake_clock)

    # Monkeypatch gazu.task.all_task_statuses
    import gazu.task

    call_count = 0

    def fake_all_statuses(client=None):
        nonlocal call_count
        call_count += 1
        return mock_statuses

    orig_all = gazu.task.all_task_statuses
    try:
        gazu.task.all_task_statuses = fake_all_statuses

        # First call fetches from API
        res1 = writer.task_statuses()
        assert res1 == mock_statuses
        assert call_count == 1

        # Second call 30s later returns cached result without API call
        current_time = 1030.0
        res2 = writer.task_statuses()
        assert res2 == mock_statuses
        assert call_count == 1

        # Third call 65s after first call invalidates cache and re-fetches
        current_time = 1065.0
        res3 = writer.task_statuses()
        assert res3 == mock_statuses
        assert call_count == 2
    finally:
        gazu.task.all_task_statuses = orig_all


def test_writer_comment_status_args():
    """comment_status passes only task, status and text to gazu.add_comment."""
    fake_client = MagicMock()
    writer = KitsuWriter(client=fake_client)

    import gazu.task

    captured_kwargs = {}

    def fake_add_comment(**kwargs):
        captured_kwargs.update(kwargs)
        return {"id": "comment-1", "text": kwargs.get("comment")}

    orig_comment = gazu.task.add_comment
    try:
        gazu.task.add_comment = fake_add_comment

        task = {"id": "task-100", "name": "Animation"}
        status = {"id": "status-200", "name": "Approved"}
        comment_text = "[AYON] Status set to 'Approved' by alice."

        res = writer.comment_status(task, status, comment_text)
        assert res["id"] == "comment-1"
        assert captured_kwargs["task"] == "task-100"
        assert captured_kwargs["task_status"] == "status-200"
        assert captured_kwargs["comment"] == comment_text
        assert captured_kwargs["client"] == fake_client
        # Ensure assignees, description, etc. are NOT passed
        assert (
            "person" not in captured_kwargs
            or captured_kwargs["person"] is None
        )
    finally:
        gazu.task.add_comment = orig_comment

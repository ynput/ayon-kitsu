"""Property test for secret redaction.

Validates: Requirements 13.6
"""

# Feature: kitsu-two-way-sync, Property 26: Secrets never appear in output

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from processor.outbound.constants import (
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    DECISION_SKIPPED,
)
from processor.outbound.describe import (
    build_log_line,
    describe_job,
    redact,
)

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

secret_text_strategy = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),
        blacklist_characters=("\x00",),
    ),
    min_size=1,
    max_size=30,
)


@settings(max_examples=100, deadline=None)
@given(
    secrets=st.lists(secret_text_strategy, min_size=1, max_size=5),
    text_prefix=st.text(max_size=20),
    text_suffix=st.text(max_size=20),
    decision=st.sampled_from(
        [
            DECISION_APPLIED,
            DECISION_SKIPPED,
            DECISION_CONFLICT,
            DECISION_FAILED,
        ]
    ),
)
def test_secrets_never_appear_in_output(
    secrets, text_prefix, text_suffix, decision
):
    """Property 26: redact excludes all non-empty secrets from text."""
    # Construct a string embedding all secrets
    embedded_text = text_prefix + "".join(secrets) + text_suffix

    redacted = redact(embedded_text, secrets)

    # Assert none of the secrets appear in the redacted output
    for s in secrets:
        if s:
            assert s not in redacted

    # Verify build_log_line and describe_job with secrets in details
    details = {
        "job_id": "job-123",
        "project_name": "test_proj",
        "entity_id": "ent-1",
        "kitsu_id": "kit-1",
        "category": "task_status",
        "message": f"failed with token {secrets[0]}",
        "reason": f"skipped with secret {secrets[-1]}",
        "secrets": secrets,
    }

    _, log_msg = build_log_line(decision, details)
    for s in secrets:
        if s:
            assert s not in log_msg

    desc = describe_job(decision, details)
    for s in secrets:
        if s:
            assert s not in desc

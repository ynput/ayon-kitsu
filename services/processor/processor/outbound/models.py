"""Shared context and structured outcomes for outbound jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, TypedDict

from .constants import DECISION_FAILED
from .describe import describe_job

if TYPE_CHECKING:
    from ..processor import KitsuProcessor
    from .identity import IdentityResolver
    from .kitsu_writer import KitsuWriter


class WriteRecord(TypedDict, total=False):
    """A successful Kitsu write, including optional assignee metadata."""

    field: str
    before: Any
    sent: Any
    action: str
    person_id: str
    person_name: str


class PendingAssigneeWrite(TypedDict):
    """An assignee request whose outcome was unknown when it returned."""

    kitsu_id: str
    write: WriteRecord


def normalize_not_written(value: Any) -> dict[str, Any]:
    """Read unwritten values, accepting records persisted by older jobs.

    Args:
        value: A field-to-value mapping or legacy field records.

    Returns:
        A fresh mapping of field names to the values that were not written.
    """
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {
            record["field"]: record.get("ayonValue")
            for record in value
            if isinstance(record, dict) and "field" in record
        }
    return {}


@dataclass
class JobContext:
    """Event, dependencies, and retry state available to a handler."""

    event: dict[str, Any]
    job_id: str
    category: str
    entity_id: str
    project_name: str
    effective_toggles: dict[str, Any]
    conflict_policy: str
    identity_resolver: IdentityResolver
    writer: KitsuWriter
    loop_guard_check: Callable[[str, str], dict[str, Any]]
    clock: Callable[[], float]
    processor: KitsuProcessor | None = None
    attempt: int = 1
    omitted_fields: list[str] = field(default_factory=list)
    kitsu_project_id: str | None = None
    loop_guard_commit: Callable[..., None] | None = None
    loop_guard_discard: Callable[[], None] | None = None
    prior_writes: list[WriteRecord] = field(default_factory=list)
    prior_not_written: dict[str, Any] = field(default_factory=dict)
    pending_assignee_write: PendingAssigneeWrite | None = None
    pending_creation_scope: dict[str, str | None] | None = None


@dataclass
class JobResult:
    """Structured handler outcome, formatted only when displayed or saved."""

    decision: str
    details: dict[str, Any] = field(default_factory=dict)
    writes: list[WriteRecord] = field(default_factory=list)
    not_written: dict[str, Any] = field(default_factory=dict)
    error_kind: str | None = None
    http_status: int | None = None
    retryable: bool = False
    kitsu_id: str | None = None
    entity_type: str | None = None
    omitted_by: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        """Format the outcome for callers inspecting a handler directly."""
        return describe_job(self.decision, self.details)


def failed_result(
    ctx: JobContext,
    reason: str,
    *,
    error: str | None = None,
    retryable: bool = False,
    error_kind: str | None = None,
    http_status: int | None = None,
    kitsu_id: str | None = None,
    entity_type: str | None = None,
    writes: list[WriteRecord] | None = None,
    not_written: dict[str, Any] | None = None,
) -> JobResult:
    """Build a failure with matching description and retry metadata.

    Args:
        ctx: Current event and attempt.
        reason: Explanation of the failed operation.
        error: Underlying error text, if different from the reason.
        retryable: Whether the job can be retried.
        error_kind: Classified error category.
        http_status: HTTP status returned by the failed request.
        kitsu_id: Target Kitsu entity, if known.
        entity_type: Target entity type for the job summary.
        writes: Writes completed before the failure.
        not_written: Values still awaiting a write.

    Returns:
        A failure containing both the reporting details and retry metadata.
    """
    writes = writes or []
    not_written = normalize_not_written(not_written)
    return JobResult(
        decision=DECISION_FAILED,
        details={
            "reason": reason,
            "error": error if error is not None else reason,
            "retryable": retryable,
            "error_kind": error_kind,
            "http_status": http_status,
            "attempt": ctx.attempt,
            "entity_id": (
                ctx.entity_id
                or (ctx.event.get("summary") or {}).get("entityId")
            ),
            "kitsu_id": kitsu_id,
            "category": ctx.category,
            "writes": writes,
            "unwritten": not_written or None,
        },
        retryable=retryable,
        error_kind=error_kind,
        http_status=http_status,
        kitsu_id=kitsu_id,
        entity_type=entity_type,
        writes=writes,
        not_written=not_written,
    )

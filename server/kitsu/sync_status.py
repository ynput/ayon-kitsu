import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from nxtools import logging

from ayon_server.lib.postgres import Postgres
from ayon_server.types import Field, OPModel

if TYPE_CHECKING:
    from .. import KitsuAddon

#: Matches ``enroll_event_job(..., max_retries=3)`` in KitsuProcessor.
SYNC_MAX_RETRIES = 3
#: Matches AYON's default 3-day ``ignore_older_than`` enrollment window.
SYNC_REQUEST_EXPIRY = timedelta(days=3)
#: Maximum age of an ASH service heartbeat before considering it stale.
PROCESSOR_HEARTBEAT_TTL = timedelta(minutes=5)

_ACTIVE_CHILD_STATUSES = frozenset({"pending", "restarted", "in_progress"})


class SyncEventInfoModel(OPModel):
    """Summary of an AYON sync event for UI status display."""

    event_id: str = Field(..., title="Event ID")
    topic: str = Field(..., title="Event topic")
    status: str = Field(..., title="Event status")
    description: str | None = Field(None, title="Event description")
    error: str | None = Field(None, title="Error message")
    updated_at: str | None = Field(None, title="Last updated timestamp")
    retries: int | None = Field(None, title="Retry attempt count")
    retryable: bool = Field(
        False, title="Whether AYON may still automatically retry this job"
    )


class ProjectSyncStatusModel(OPModel):
    """Per-project sync status snapshot."""

    project_name: str = Field(..., title="AYON project name")
    kitsu_project_id: str | None = Field(None, title="Kitsu project ID")
    full_sync: SyncEventInfoModel | None = Field(
        None, title="Latest full sync status"
    )
    last_inbound_error: SyncEventInfoModel | None = Field(
        None, title="Latest inbound sync error"
    )


class SyncStatusResponseModel(OPModel):
    """Aggregated Kitsu sync status for all paired projects and processor."""

    projects: dict[str, ProjectSyncStatusModel] = Field(
        default_factory=dict,
        title="Sync status keyed by AYON project name",
    )
    processor_running: bool | None = Field(
        None, title="Whether a managed Kitsu processor service is running"
    )
    last_service_error: SyncEventInfoModel | None = Field(
        None, title="Most recent Kitsu processor log.error event"
    )


def _parse_json_dict(raw: Any) -> dict[str, Any]:
    """Safely normalize a Postgres jsonb value into a dictionary.

    Args:
        raw: Value returned from Postgres (dict, JSON string, or None).

    Returns:
        Parsed dictionary, or an empty dict if parsing fails.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _to_utc_datetime(value: Any) -> datetime | None:
    """Parse a datetime or ISO-8601 string into an aware UTC datetime.

    Args:
        value: Datetime object, ISO string, or None.

    Returns:
        Timezone-aware UTC datetime, or None if unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _format_timestamp(value: Any) -> str | None:
    """Format a datetime or string timestamp as an ISO-8601 string.

    Args:
        value: Datetime object, ISO string, or None.

    Returns:
        ISO-8601 string or None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _extract_error(payload: Any) -> str | None:
    """Extract a human-readable error message from an event payload.

    Args:
        payload: Event payload dict or JSON string.

    Returns:
        Error string when present, else None.
    """
    data = _parse_json_dict(payload)
    for key in ("error", "message"):
        val = data.get(key)
        if val:
            return str(val)
    return None


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    """Read an optional column from a Postgres Record or dict safely.

    Args:
        row: Record or mapping returned by Postgres.
        key: Column name.
        default: Value returned when key is absent.

    Returns:
        Column value or default.
    """
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _is_service_alive(row: Any, now_utc: datetime) -> bool:
    """Check whether a managed service row reports a live, recent heartbeat.

    Args:
        row: Row from ``services`` table with ``is_running`` and ``last_seen``.
        now_utc: Current UTC timestamp.

    Returns:
        True only when ``is_running`` is true and ``last_seen`` is within
        ``PROCESSOR_HEARTBEAT_TTL``.
    """
    if not bool(_row_get(row, "is_running", False)):
        return False
    last_seen = _to_utc_datetime(_row_get(row, "last_seen"))
    if last_seen is None:
        return False
    return (now_utc - last_seen) <= PROCESSOR_HEARTBEAT_TTL


def _is_request_expired(row: Any, now_utc: datetime) -> bool:
    """Return True if a ``kitsu.sync_request`` exceeded AYON's 3-day window.

    Args:
        row: ``kitsu.sync_request`` row from ``events``.
        now_utc: Current UTC timestamp.

    Returns:
        True when ``updated_at`` is older than ``SYNC_REQUEST_EXPIRY``.
    """
    updated = _to_utc_datetime(_row_get(row, "updated_at"))
    if updated is None:
        return False
    return (now_utc - updated) > SYNC_REQUEST_EXPIRY


def _row_to_event_info(
    row: Any,
    *,
    status_override: str | None = None,
    description_override: str | None = None,
    check_retryable: bool = False,
    source_expired: bool = False,
) -> SyncEventInfoModel:
    """Convert an ``events`` table row into ``SyncEventInfoModel``.

    Args:
        row: Mapping/Record from Postgres ``events`` table.
        status_override: Optional status override (e.g. ``pending`` or
            ``expired``).
        description_override: Optional description override.
        check_retryable: Whether to compute ``retryable`` from ``retries``
            and ``depends_on`` for ``kitsu.sync`` jobs.
        source_expired: True when the parent ``kitsu.sync_request`` has aged
            out of AYON's enrollment window and will not be re-enrolled.

    Returns:
        Serialized ``SyncEventInfoModel`` instance.
    """
    status = status_override or str(row["status"])
    description = (
        description_override
        if description_override is not None
        else row["description"]
    )
    raw_retries = _row_get(row, "retries")
    retries = raw_retries if isinstance(raw_retries, int) else None
    depends_on = _row_get(row, "depends_on")

    if source_expired and status == "restarted":
        status = "expired"
        description = (
            "Sync request expired before processor enrolled it; "
            "click Sync now to retry."
        )

    retryable = bool(
        check_retryable
        and not source_expired
        and status == "failed"
        and depends_on is not None
        and retries is not None
        and retries <= SYNC_MAX_RETRIES
    )
    return SyncEventInfoModel(
        event_id=str(row["id"]),
        topic=str(row["topic"]),
        status=status,
        description=description,
        error=_extract_error(row["payload"]),
        updated_at=_format_timestamp(row["updated_at"]),
        retries=retries,
        retryable=retryable,
    )


def _is_manual_child_active(row: Any, source_expired: bool) -> bool:
    """Return True if a manual ``kitsu.sync`` child job is still active.

    Args:
        row: ``kitsu.sync`` row linked to a ``kitsu.sync_request``.
        source_expired: Whether the parent ``kitsu.sync_request`` expired.

    Returns:
        True if the job is pending, in progress, or still eligible for
        enrollment/retry.
    """
    if source_expired:
        return False
    status = str(row["status"])
    if status in _ACTIVE_CHILD_STATUSES:
        return True
    raw_retries = _row_get(row, "retries")
    return (
        status == "failed"
        and _row_get(row, "depends_on") is not None
        and isinstance(raw_retries, int)
        and raw_retries <= SYNC_MAX_RETRIES
    )


def _resolve_project_full_sync(
    sync_row: Any | None,
    req_row: Any | None,
    manual_sync_row: Any | None,
    now_utc: datetime,
) -> SyncEventInfoModel | None:
    """Resolve the authoritative full-sync status for one project.

    Keeps an unexpired queued or active manual request visible even if an
    independent startup ``kitsu.sync`` ran in the meantime, and prevents
    expired source requests from keeping ``Sync now`` permanently disabled.

    Args:
        sync_row: Latest ``kitsu.sync`` event for the project (manual or
            startup).
        req_row: Latest ``kitsu.sync_request`` event for the project.
        manual_sync_row: ``kitsu.sync`` child job linked to ``req_row``, if
            already enrolled.
        now_utc: Current UTC timestamp.

    Returns:
        Resolved ``SyncEventInfoModel`` or None if never synced.
    """
    req_expired = (
        _is_request_expired(req_row, now_utc) if req_row is not None else False
    )

    # 1. Unenrolled manual request: keep it visible while unexpired so a
    #    newer startup kitsu.sync never masks the queued manual request.
    if req_row is not None and manual_sync_row is None:
        if not req_expired:
            return _row_to_event_info(
                req_row,
                status_override="pending",
                description_override=(
                    "Sync queued, waiting for Kitsu processor..."
                ),
            )
        # Request expired without enrollment: show a newer startup sync if one
        # ran after the request, otherwise mark the request expired/retryable.
        req_ts = _to_utc_datetime(req_row["updated_at"])
        sync_ts = (
            _to_utc_datetime(sync_row["updated_at"])
            if sync_row is not None
            else None
        )
        if sync_row is not None and (
            req_ts is None or (sync_ts is not None and sync_ts > req_ts)
        ):
            return _row_to_event_info(sync_row, check_retryable=True)
        return _row_to_event_info(
            req_row,
            status_override="expired",
            description_override=(
                "Sync request expired before processor enrolled it; "
                "click Sync now to retry."
            ),
        )

    # 2. Enrolled manual job still active (queued, restarted, in progress, or
    #    retrying): keep it visible over any independent startup sync.
    if manual_sync_row is not None and _is_manual_child_active(
        manual_sync_row, req_expired
    ):
        return _row_to_event_info(
            manual_sync_row,
            check_retryable=True,
            source_expired=req_expired,
        )

    # 3. Otherwise show the latest kitsu.sync row (manual or startup),
    #    accounting for whether its parent sync_request has expired.
    chosen = sync_row if sync_row is not None else manual_sync_row
    if chosen is None:
        return None
    chosen_source_expired = bool(
        req_row is not None
        and req_expired
        and str(_row_get(chosen, "depends_on") or "") == str(req_row["id"])
    )
    return _row_to_event_info(
        chosen,
        check_retryable=True,
        source_expired=chosen_source_expired,
    )


async def get_sync_status(addon: "KitsuAddon") -> SyncStatusResponseModel:
    """Collect current Kitsu sync status for paired projects and processor.

    Args:
        addon: Active Kitsu server addon instance.

    Returns:
        Aggregated status response containing per-project full/inbound sync
        states and processor health.
    """
    now_utc = datetime.now(timezone.utc)
    projects: dict[str, ProjectSyncStatusModel] = {}

    project_rows = await Postgres.fetch(
        """
        SELECT
            name,
            data->>'kitsuProjectId' AS kitsu_project_id
        FROM projects
        WHERE data->>'kitsuProjectId' IS NOT NULL
        """
    )

    for row in project_rows:
        project_name = row["name"]
        projects[project_name] = ProjectSyncStatusModel(
            project_name=project_name,
            kitsu_project_id=row["kitsu_project_id"],
        )

    if projects:
        project_names = list(projects.keys())

        # Latest kitsu.sync job per project (manual or startup)
        sync_rows = await Postgres.fetch(
            """
            SELECT DISTINCT ON (project_name)
                id, topic, project_name, depends_on, status, retries,
                description, payload, updated_at
            FROM events
            WHERE topic = 'kitsu.sync'
              AND project_name = ANY($1)
            ORDER BY project_name, updated_at DESC
            """,
            project_names,
        )
        sync_by_project = {row["project_name"]: row for row in sync_rows}

        # Latest kitsu.sync_request per project
        req_rows = await Postgres.fetch(
            """
            SELECT DISTINCT ON (project_name)
                id, topic, project_name, status,
                description, payload, updated_at
            FROM events
            WHERE topic = 'kitsu.sync_request'
              AND project_name = ANY($1)
            ORDER BY project_name, updated_at DESC
            """,
            project_names,
        )
        req_by_project = {row["project_name"]: row for row in req_rows}

        # Child kitsu.sync jobs matching the latest kitsu.sync_request per
        # project, so startup syncs cannot mask queued manual requests.
        manual_by_project: dict[str, Any] = {}
        req_ids = [str(row["id"]) for row in req_rows]
        if req_ids:
            child_rows = await Postgres.fetch(
                """
                SELECT DISTINCT ON (depends_on)
                    id, topic, project_name, depends_on, status, retries,
                    description, payload, updated_at
                FROM events
                WHERE topic = 'kitsu.sync'
                  AND depends_on = ANY($1)
                ORDER BY depends_on, updated_at DESC
                """,
                req_ids,
            )
            child_by_req_id = {
                str(row["depends_on"]): row for row in child_rows
            }
            for project_name, req_row in req_by_project.items():
                child = child_by_req_id.get(str(req_row["id"]))
                if child is not None:
                    manual_by_project[project_name] = child

        for project_name, model in projects.items():
            model.full_sync = _resolve_project_full_sync(
                sync_by_project.get(project_name),
                req_by_project.get(project_name),
                manual_by_project.get(project_name),
                now_utc,
            )

        # Latest failed inbound event per project
        inbound_err_rows = await Postgres.fetch(
            """
            SELECT DISTINCT ON (project_name)
                id, topic, project_name, status,
                description, payload, updated_at
            FROM events
            WHERE topic = 'kitsu.inbound_sync'
              AND status = 'failed'
              AND project_name = ANY($1)
            ORDER BY project_name, updated_at DESC
            """,
            project_names,
        )
        for row in inbound_err_rows:
            model = projects.get(row["project_name"])
            if model is not None:
                model.last_inbound_error = _row_to_event_info(row)

    # Check managed Kitsu processor service health using heartbeat freshness.
    # Return None (unknown) when no managed service rows exist (e.g. a local
    # standalone processor launched via manage.ps1).
    processor_running: bool | None = None
    try:
        service_rows = await Postgres.fetch(
            """
            SELECT is_running, last_seen
            FROM services
            WHERE addon_name = $1
            """,
            addon.name,
        )
        if service_rows:
            processor_running = any(
                _is_service_alive(row, now_utc) for row in service_rows
            )
    except Exception as exc:
        logging.debug(f"Unable to query Kitsu service status: {exc}")

    # Check most recent Kitsu processor log.error event (last 24 hours)
    last_service_error: SyncEventInfoModel | None = None
    try:
        err_rows = await Postgres.fetch(
            """
            SELECT id, topic, status, description, payload, updated_at
            FROM events
            WHERE topic = 'log.error'
              AND (
                  sender LIKE 'kitsu-processor%'
                  OR description LIKE 'Kitsu processor%'
              )
              AND updated_at > NOW() - INTERVAL '24 hours'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        if err_rows:
            last_service_error = _row_to_event_info(err_rows[0])
    except Exception as exc:
        logging.debug(f"Unable to query Kitsu service errors: {exc}")

    return SyncStatusResponseModel(
        projects=projects,
        processor_running=processor_running,
        last_service_error=last_service_error,
    )

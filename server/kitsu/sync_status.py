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
    last_outbound: SyncEventInfoModel | None = Field(
        None, title="Latest outbound sync event"
    )
    last_inbound_error: SyncEventInfoModel | None = Field(
        None, title="Latest inbound sync error"
    )
    two_way_sync_enabled: bool = Field(
        False, title="Whether two-way sync is enabled for the project"
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
    """Return True if an unenrolled ``kitsu.sync_request`` exceeded 3 days.

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
) -> SyncEventInfoModel:
    """Convert an ``events`` table row into ``SyncEventInfoModel``.

    Args:
        row: Mapping/Record from Postgres ``events`` table.
        status_override: Optional status override (e.g. ``pending`` for an
            unenrolled ``kitsu.sync_request``).
        description_override: Optional description override.
        check_retryable: Whether to compute ``retryable`` from ``retries``
            and ``depends_on`` for ``kitsu.sync`` jobs.

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
    retryable = bool(
        check_retryable
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


async def get_sync_status(
    addon: "KitsuAddon",
    *,
    include_settings: bool = True,
) -> SyncStatusResponseModel:
    """Collect current Kitsu sync status for paired projects and processor.

    Args:
        addon: Active Kitsu server addon instance.
        include_settings: When True, resolve per-project ``two_way_sync``
            settings. Callers on fast polling loops may set this to False to
            avoid redundant settings queries.

    Returns:
        Aggregated status response containing per-project full/outbound/inbound
        sync states and processor health.
    """
    now_utc = datetime.now(timezone.utc)
    projects: dict[str, ProjectSyncStatusModel] = {}

    # Fetch paired projects into memory first so the DB connection is released
    # before any per-project settings lookups run.
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
        two_way_enabled = False
        if include_settings:
            try:
                proj_settings = await addon.get_project_settings(project_name)
                sync_settings = getattr(proj_settings, "sync_settings", None)
                two_way = getattr(sync_settings, "two_way_sync", None)
                two_way_enabled = bool(getattr(two_way, "enabled", False))
            except Exception as exc:
                logging.debug(
                    f"Unable to read two-way sync setting for "
                    f"{project_name}: {exc}"
                )

        projects[project_name] = ProjectSyncStatusModel(
            project_name=project_name,
            kitsu_project_id=row["kitsu_project_id"],
            two_way_sync_enabled=two_way_enabled,
        )

    if projects:
        project_names = list(projects.keys())

        # Latest kitsu.sync job per project
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

        # Latest kitsu.sync_request per project (covers newly queued syncs
        # before the processor enrolls a kitsu.sync child job)
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

        for project_name, model in projects.items():
            sync_row = sync_by_project.get(project_name)
            req_row = req_by_project.get(project_name)

            use_request_row = False
            if sync_row is not None and req_row is not None:
                req_ts = _to_utc_datetime(req_row["updated_at"])
                sync_ts = _to_utc_datetime(sync_row["updated_at"])
                use_request_row = (
                    str(sync_row["depends_on"] or "") != str(req_row["id"])
                    and req_ts is not None
                    and sync_ts is not None
                    and req_ts > sync_ts
                )
            elif sync_row is None and req_row is not None:
                use_request_row = True

            if use_request_row and req_row is not None:
                if _is_request_expired(req_row, now_utc):
                    model.full_sync = _row_to_event_info(
                        req_row,
                        status_override="expired",
                        description_override=(
                            "Sync request expired before processor enrolled "
                            "it; click Sync now to retry."
                        ),
                    )
                else:
                    model.full_sync = _row_to_event_info(
                        req_row,
                        status_override="pending",
                        description_override=(
                            "Sync queued, waiting for Kitsu processor..."
                        ),
                    )
            elif sync_row is not None:
                model.full_sync = _row_to_event_info(
                    sync_row, check_retryable=True
                )

        # Latest outbound sync job per project
        outbound_rows = await Postgres.fetch(
            """
            SELECT DISTINCT ON (project_name)
                id, topic, project_name, status,
                description, payload, updated_at
            FROM events
            WHERE topic = 'kitsu.outbound_sync'
              AND project_name = ANY($1)
            ORDER BY project_name, updated_at DESC
            """,
            project_names,
        )
        for row in outbound_rows:
            model = projects.get(row["project_name"])
            if model is not None:
                model.last_outbound = _row_to_event_info(row)

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

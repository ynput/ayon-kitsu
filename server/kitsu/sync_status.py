import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nxtools import logging

from ayon_server.lib.postgres import Postgres
from ayon_server.types import Field, OPModel

if TYPE_CHECKING:
    from .. import KitsuAddon


class SyncEventInfoModel(OPModel):
    """Summary of an AYON sync event for UI status display."""

    event_id: str = Field(..., title="Event ID")
    topic: str = Field(..., title="Event topic")
    status: str = Field(..., title="Event status")
    description: str | None = Field(None, title="Event description")
    error: str | None = Field(None, title="Error message")
    updated_at: str | None = Field(None, title="Last updated timestamp")


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
        None, title="Whether a Kitsu processor service is running"
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


def _row_to_event_info(
    row: Any,
    *,
    status_override: str | None = None,
    description_override: str | None = None,
) -> SyncEventInfoModel:
    """Convert an ``events`` table row into ``SyncEventInfoModel``.

    Args:
        row: Mapping/Record from Postgres ``events`` table.
        status_override: Optional status override (e.g. ``pending`` for an
            unenrolled ``kitsu.sync_request``).
        description_override: Optional description override.

    Returns:
        Serialized ``SyncEventInfoModel`` instance.
    """
    status = status_override or str(row["status"])
    description = (
        description_override
        if description_override is not None
        else row["description"]
    )
    return SyncEventInfoModel(
        event_id=str(row["id"]),
        topic=str(row["topic"]),
        status=status,
        description=description,
        error=_extract_error(row["payload"]),
        updated_at=_format_timestamp(row["updated_at"]),
    )


async def get_sync_status(addon: "KitsuAddon") -> SyncStatusResponseModel:
    """Collect current Kitsu sync status for paired projects and processor.

    Args:
        addon: Active Kitsu server addon instance.

    Returns:
        Aggregated status response containing per-project full/outbound/inbound
        sync states and processor health.
    """
    projects: dict[str, ProjectSyncStatusModel] = {}

    async for row in Postgres.iterate(
        """
        SELECT
            name,
            data->>'kitsuProjectId' AS kitsu_project_id
        FROM projects
        WHERE data->>'kitsuProjectId' IS NOT NULL
        """
    ):
        project_name = row["name"]
        two_way_enabled = False
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
                id, topic, project_name, depends_on, status,
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

            if sync_row is not None:
                req_is_newer_and_unenrolled = (
                    req_row is not None
                    and str(sync_row["depends_on"] or "") != str(req_row["id"])
                    and req_row["updated_at"] is not None
                    and sync_row["updated_at"] is not None
                    and req_row["updated_at"] > sync_row["updated_at"]
                )
                if req_is_newer_and_unenrolled:
                    model.full_sync = _row_to_event_info(
                        req_row,
                        status_override="pending",
                        description_override=(
                            "Sync queued, waiting for Kitsu processor..."
                        ),
                    )
                else:
                    model.full_sync = _row_to_event_info(sync_row)
            elif req_row is not None:
                model.full_sync = _row_to_event_info(
                    req_row,
                    status_override="pending",
                    description_override=(
                        "Sync queued, waiting for Kitsu processor..."
                    ),
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

    # Check whether a Kitsu processor service is running
    processor_running: bool | None = None
    try:
        service_rows = await Postgres.fetch(
            """
            SELECT is_running
            FROM services
            WHERE addon_name = $1
            """,
            addon.name,
        )
        processor_running = any(bool(r["is_running"]) for r in service_rows)
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

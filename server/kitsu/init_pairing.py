import hashlib
from typing import TYPE_CHECKING

from ayon_server.entities import UserEntity
from ayon_server.events import dispatch_event, update_event
from ayon_server.exceptions import BadRequestException, ConflictException
from ayon_server.helpers.deploy_project import create_project_from_anatomy
from ayon_server.lib.postgres import Postgres
from ayon_server.types import (
    PROJECT_CODE_REGEX,
    PROJECT_NAME_REGEX,
    Field,
    OPModel,
)

from .anatomy import get_kitsu_project_anatomy

if TYPE_CHECKING:
    from .. import KitsuAddon


class InitPairingRequest(OPModel):
    kitsu_project_id: str = Field(..., title="Kitsu project ID")
    ayon_project_name: str = Field(
        "...",
        title="Ayon project name",
        regex=PROJECT_NAME_REGEX,
    )
    ayon_project_code: str = Field(
        ...,
        title="Ayon project code",
        regex=PROJECT_CODE_REGEX,
    )
    # anatomy_preset: str | None = Field(None, title="Anatomy preset")


class SyncRequestResponseModel(OPModel):
    """Response payload returned when a Kitsu full sync is queued."""

    event_id: str = Field(..., title="Sync request event ID")
    sync_event_id: str | None = Field(None, title="Sync job event ID")
    project_name: str = Field(..., title="AYON project name")
    kitsu_project_id: str = Field(..., title="Kitsu project ID")
    status: str = Field(..., title="Sync request status")


async def ensure_ayon_project_not_exists(project_name: str, project_code: str):
    async for _ in Postgres.iterate(
        "SELECT name FROM projects WHERE name = $1 OR code = $2",
        project_name,
        project_code,
    ):
        raise ConflictException(f"Project {project_name} already exists")
    return None


async def sync_request(
    project_name: str,
    user: UserEntity,
    kitsu_project_id: str | None = None,
) -> SyncRequestResponseModel:
    """Queue or restart a Kitsu full-sync job for a paired AYON project.

    Args:
        project_name: Name of the AYON project to sync.
        user: Authenticated AYON user initiating the sync.
        kitsu_project_id: Optional Kitsu project ID; resolved from project
            metadata when omitted.

    Returns:
        Structured metadata containing the queued event IDs and status.

    Raises:
        BadRequestException: If the AYON project does not exist or is not
            paired with a Kitsu project.
    """
    if kitsu_project_id is None:
        async for res in Postgres.iterate(
            "SELECT data->>'kitsuProjectId' as kitsu_project_id "
            "FROM projects WHERE name = $1",
            project_name,
        ):
            kitsu_project_id = res["kitsu_project_id"]

    if not kitsu_project_id:
        raise BadRequestException(
            f"Project '{project_name}' is not paired with a Kitsu project"
        )

    hash = hashlib.sha256(
        f"kitsu_sync_{project_name}_{kitsu_project_id}".encode("utf-8")
    ).hexdigest()

    query = """
        SELECT id FROM events
        WHERE hash = $1
    """

    res = await Postgres.fetch(query, hash)

    if res:
        event_id = str(res[0][0])
        await update_event(
            event_id,
            description="Sync request from Kitsu",
            project=project_name,
            user=user.name,
        )

        sync_rows = await Postgres.fetch(
            """
            UPDATE events SET
                updated_at = NOW(),
                status = 'restarted',
                retries = 0,
                description = 'Sync queued, waiting for Kitsu processor...',
                payload = '{}'::jsonb
            WHERE topic = 'kitsu.sync'
            AND depends_on = $1
            RETURNING id
            """,
            event_id,
        )
        sync_event_id = str(sync_rows[0][0]) if sync_rows else None
        return SyncRequestResponseModel(
            event_id=event_id,
            sync_event_id=sync_event_id,
            project_name=project_name,
            kitsu_project_id=kitsu_project_id,
            status="restarted" if sync_event_id else "pending",
        )

    event_id = await dispatch_event(
        "kitsu.sync_request",
        hash=hash,
        description="Sync request from Kitsu",
        project=project_name,
        user=user.name,
        summary={
            "kitsuProjectId": kitsu_project_id,
        },
    )
    return SyncRequestResponseModel(
        event_id=str(event_id),
        sync_event_id=None,
        project_name=project_name,
        kitsu_project_id=kitsu_project_id,
        status="pending",
    )


async def init_pairing(
    addon: "KitsuAddon",
    user: "UserEntity",
    request: InitPairingRequest,
) -> SyncRequestResponseModel:
    """Create and pair an AYON project with a Kitsu project, then queue sync.

    Args:
        addon: Active Kitsu server addon instance.
        user: Authenticated AYON user creating the pairing.
        request: Pairing payload with Kitsu project ID and AYON name/code.

    Returns:
        Structured metadata for the initial queued full-sync event.
    """
    await ensure_ayon_project_not_exists(
        request.ayon_project_name,
        request.ayon_project_code,
    )

    anatomy = await get_kitsu_project_anatomy(addon, request.kitsu_project_id)

    await create_project_from_anatomy(
        name=request.ayon_project_name,
        code=request.ayon_project_code,
        anatomy=anatomy,
        library=False,
    )

    prj_data = {
        "kitsuProjectId": request.kitsu_project_id,
    }

    await Postgres.execute(
        """UPDATE projects SET data=$1 WHERE name=$2""",
        prj_data,
        request.ayon_project_name,
    )

    return await sync_request(
        project_name=request.ayon_project_name,
        user=user,
        kitsu_project_id=request.kitsu_project_id,
    )

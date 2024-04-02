import hashlib
from typing import TYPE_CHECKING

from ayon_server.entities import UserEntity
from ayon_server.events import dispatch_event, update_event
from ayon_server.exceptions import ConflictException
from ayon_server.helpers.deploy_project import create_project_from_anatomy
from ayon_server.lib.postgres import Postgres
from ayon_server.types import PROJECT_CODE_REGEX, PROJECT_NAME_REGEX, Field, OPModel

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
    mock: bool | None = None
    # anatomy_preset: str | None = Field(None, title="Anatomy preset")


async def ensure_ayon_project_not_exists(project_name: str, project_code: str):
    async for res in Postgres.iterate(
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
):
    if kitsu_project_id is None:
        async for res in Postgres.iterate(
            "SELECT data->>'kitsuProjectId' FROM projects WHERE name = $1",
            project_name,
        ):
            kitsu_project_id = res[0]

    hash = hashlib.sha256(
        f"kitsu_sync_{project_name}_{kitsu_project_id}".encode("utf-8")
    ).hexdigest()

    query = """
        SELECT id FROM events
        WHERE hash = $1
    """

    res = await Postgres.fetch(query, hash)

    if res:
        await update_event(
            res[0][0],
            description="Sync request from Kitsu",
            project=project_name,
            user=user.name,
        )

        await Postgres.execute(
            """
            UPDATE events SET
                updated_at = NOW(),
                status = 'restarted',
                retries = 0
            WHERE topic = 'kitsu.sync'
            AND depends_on = $1
            """,
            res[0][0],
        )
    else:
        await dispatch_event(
            "kitsu.sync_request",
            hash=hash,
            description="Sync request from Kitsu",
            project=project_name,
            user=user.name,
            summary={
                "kitsuProjectId": kitsu_project_id,
            },
        )


async def init_pairing(
    addon: "KitsuAddon",
    user: "UserEntity",
    request: InitPairingRequest,
):
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

    await sync_request(
        project_name=request.ayon_project_name,
        user=user,
        kitsu_project_id=request.kitsu_project_id,
    )

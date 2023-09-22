from typing import TYPE_CHECKING

from ayon_server.entities import UserEntity
from ayon_server.events import dispatch_event
from ayon_server.exceptions import ConflictException
from ayon_server.helpers.deploy_project import create_project_from_anatomy
from ayon_server.lib.postgres import Postgres
from ayon_server.types import OPModel, Field, PROJECT_NAME_REGEX, PROJECT_CODE_REGEX

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


async def ensure_ayon_project_not_exists(project_name: str, project_code: str):
    async for res in Postgres.iterate(
        "SELECT name FROM projects WHERE name = $1 OR code = $2",
        project_name,
        project_code,
    ):
        raise ConflictException(f"Project {project_name} already exists")
    return None


async def init_pairing(
    addon: "KitsuAddon",
    user: "UserEntity",
    request: InitPairingRequest,
):
    await ensure_ayon_project_not_exists(
        request.ayon_project_name, request.ayon_project_code
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

    await dispatch_event(
        "kitsu.sync_request",
        description="Imported project from Kitsu",
        user=user.name,
        project=request.ayon_project_name,
        summary={
            "kitsuProjectId": request.kitsu_project_id,
        }
    )

from typing import TYPE_CHECKING

from ayon_server.exceptions import AyonException
from ayon_server.lib.postgres import Postgres
from ayon_server.types import Field, OPModel

if TYPE_CHECKING:
    from .. import KitsuAddon


class PairingItemModel(OPModel):
    kitsu_project_id: str = Field(..., title="Kitsu project ID")
    kitsu_project_name: str = Field(..., title="Kitsu project name")
    kitsu_project_code: str | None = Field(None, title="Kitsu project code")
    ayon_project_name: str | None = Field(..., title="Ayon project name")


async def get_pairing_list(addon: "KitsuAddon") -> list[PairingItemModel]:
    #
    # Load kitsu projects
    #
    # return vars(addon)
    kitsu_projects_response = await addon.kitsu.get("data/projects")

    if kitsu_projects_response.status_code != 200:
        raise AyonException(
            status=kitsu_projects_response.status_code,
            detail="Could not get Kitsu projects",
        )

    kitsu_projects = kitsu_projects_response.json()

    #
    # load ayon projects
    #

    # pairing: kitsu_project_id -> ayon_project_name

    ayon_projects: dict[str, str] = {}
    async for res in Postgres.iterate(
        """
        SELECT
            name,
            data->>'kitsuProjectId' AS kitsu_project_id
        FROM projects
        WHERE data->>'kitsuProjectId' IS NOT NULL
        """
    ):
        ayon_projects[res["kitsu_project_id"]] = res["name"]

    #
    # compare kitsu and ayon projects
    #

    result: list[PairingItemModel] = []

    for project in kitsu_projects:
        result.append(
            PairingItemModel(
                kitsu_project_id=project["id"],
                kitsu_project_name=project["name"],
                kitsu_project_code=project.get("code"),
                ayon_project_name=ayon_projects.get(project["id"]),
            )
        )

    return result

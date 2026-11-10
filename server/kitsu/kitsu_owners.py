"""Read-only lookup of the AYON entities that own a given Kitsu id.

The Processor uses this for duplicate detection during outbound identity
resolution (Requirement 3.8). GraphQL cannot filter by ``data`` efficiently,
so the lookup queries ``data->>'kitsuId'`` directly.
"""

from ayon_server.entities import ProjectEntity
from ayon_server.exceptions import BadRequestException
from ayon_server.lib.postgres import Postgres
from ayon_server.types import Field, OPModel

from .utils import _ensure_safe_project_name


class KitsuOwnersModel(OPModel):
    """AYON entities whose ``data.kitsuId`` equals the requested Kitsu id."""

    folders: list[str] = Field(
        default_factory=list, title="AYON folder ids owning the Kitsu id"
    )
    tasks: list[str] = Field(
        default_factory=list, title="AYON task ids owning the Kitsu id"
    )
    users: list[str] = Field(
        default_factory=list, title="AYON user names owning the Kitsu id"
    )


async def get_kitsu_owners(
    project_name: str,
    kitsu_id: str,
) -> KitsuOwnersModel:
    """Return every folder, task and user that stores ``kitsu_id``.

    The project name is validated against ``NAME_REGEX`` before it is used
    as part of the ``project_<name>`` schema name, and the project must
    exist. The Kitsu id is only ever passed as a query parameter.

    Args:
        project_name: AYON project name whose folders and tasks are searched.
        kitsu_id: Kitsu entity id to look up in ``data->>'kitsuId'``.

    Returns:
        The ids of matching folders and tasks in the project and the names
        of matching users. Lists are sorted and empty when nothing matches.

    Raises:
        BadRequestException: If ``project_name`` is not a valid AYON project
            name or ``kitsu_id`` is empty.
        NotFoundException: If the project does not exist (raised by
            ``ProjectEntity.load``).
    """
    try:
        _ensure_safe_project_name(project_name)
    except ValueError as exc:
        raise BadRequestException(str(exc)) from exc

    if not kitsu_id or not kitsu_id.strip():
        raise BadRequestException("kitsu_id must not be empty")

    # Same behavior as /push and /remove: an unknown project is a 404.
    project = await ProjectEntity.load(project_name)
    schema = f"project_{project.name}"

    folder_rows = await Postgres.fetch(
        f"""
        SELECT id FROM {schema}.folders
        WHERE data->>'kitsuId' = $1
        ORDER BY id
        """,
        kitsu_id,
    )
    task_rows = await Postgres.fetch(
        f"""
        SELECT id FROM {schema}.tasks
        WHERE data->>'kitsuId' = $1
        ORDER BY id
        """,
        kitsu_id,
    )
    user_rows = await Postgres.fetch(
        """
        SELECT name FROM public.users
        WHERE data->>'kitsuId' = $1
        ORDER BY name
        """,
        kitsu_id,
    )

    return KitsuOwnersModel(
        folders=[str(row["id"]) for row in folder_rows],
        tasks=[str(row["id"]) for row in task_rows],
        users=[row["name"] for row in user_rows],
    )

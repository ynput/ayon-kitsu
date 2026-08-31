from ayon_server.lib.postgres import Postgres
from ayon_server.types import Field, OPModel


class UserSyncInfoModel(OPModel):
    """Minimal user data needed by the processor for person change matching."""

    name: str = Field(..., title="AYON username")
    kitsu_id: str | None = Field(
        None, title="Kitsu person ID stored in user data"
    )
    email: str | None = Field(None, title="Email address")
    full_name: str | None = Field(None, title="Full name")
    active: bool = Field(True, title="Whether the user is active in AYON")


async def get_user_sync_list() -> list[UserSyncInfoModel]:
    """Return all AYON users with the fields to detect Kitsu person changes.

    Queries the database directly so that ``data->>'kitsuId'`` is available,
    which is not exposed by the GraphQL ``UserNode`` schema.  Both active and
    inactive users are returned so that Kitsu deactivations can be detected and
    mirrored to AYON.
    """
    result: list[UserSyncInfoModel] = []
    async for row in Postgres.iterate("""
        SELECT
            name,
            data->>'kitsuId'          AS kitsu_id,
            attrib->>'email'          AS email,
            attrib->>'fullName'       AS full_name,
            active
        FROM public.users
        """):
        result.append(UserSyncInfoModel(**dict(row)))
    return result

"""Tests for the addon's Kitsu user lookup.

Transient database errors must propagate; only a missing user
returns ``None``.
"""

import pytest

from .offline import block_network  # noqa: F401
from unittest.mock import MagicMock

pytestmark = pytest.mark.usefixtures("block_network")


def test_get_user_by_kitsu_id_propagates_non_not_found_errors():
    """get_user_by_kitsu_id raises on transient DB error,
    and returns None on 404.
    """
    import sys
    import types

    def run_coro(coro):
        try:
            coro.send(None)
        except StopIteration as exc:
            return exc.value

    for p in [
        "ayon_server",
        "ayon_server.api",
        "ayon_server.lib",
        "ayon_server.auth",
    ]:
        if p not in sys.modules:
            m = types.ModuleType(p)
            m.__path__ = []
            sys.modules[p] = m

    for sub in [
        "ayon_server.entities",
        "ayon_server.events",
        "ayon_server.lib.postgres",
        "ayon_server.types",
        "ayon_server.auth.session",
        "ayon_server.api.context",
        "ayon_server.exceptions",
    ]:
        if sub not in sys.modules:
            sys.modules[sub] = MagicMock()

    class AyonNotFound(Exception):
        pass

    sys.modules["ayon_server.exceptions"].NotFoundException = AyonNotFound

    if "server" not in sys.modules:
        server_mod = types.ModuleType("server")
        server_mod.__path__ = ["server"]
        sys.modules["server"] = server_mod

    if "server.kitsu" not in sys.modules:
        kitsu_mod = types.ModuleType("server.kitsu")
        kitsu_mod.__path__ = ["server/kitsu"]
        sys.modules["server.kitsu"] = kitsu_mod
        sys.modules["server"].kitsu = kitsu_mod

    import server.kitsu.attrib_parsing  # noqa: F401
    import server.kitsu.constants  # noqa: F401
    import server.kitsu.utils as kitsu_utils

    class CustomNotFound(Exception):
        status_code = 404

    # 1. DB returns user row, but UserEntity.load raises transient DB error
    async def mock_fetch(*args, **kwargs):
        return [{"name": "alice"}]

    kitsu_utils.Postgres.fetch = mock_fetch

    async def mock_load_err(name):
        raise RuntimeError("Transient DB connection loss")

    kitsu_utils.UserEntity.load = mock_load_err

    with pytest.raises(RuntimeError, match="Transient DB connection loss"):
        run_coro(kitsu_utils.get_user_by_kitsu_id("kitsu-u1"))

    # 2. When UserEntity.load raises 404 / NotFound, returns None
    async def mock_load_404(name):
        raise CustomNotFound("User not found")

    kitsu_utils.UserEntity.load = mock_load_404
    result = run_coro(kitsu_utils.get_user_by_kitsu_id("kitsu-u1"))
    assert result is None

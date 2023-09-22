from typing import Type

# from fastapi import BackgroundTasks


from ayon_server.addons import BaseServerAddon
from ayon_server.api.dependencies import CurrentUser
from ayon_server.api.responses import EmptyResponse
from ayon_server.exceptions import InvalidSettingsException, ForbiddenException
from ayon_server.secrets import Secrets

from .version import __version__
from .settings import KitsuSettings, DEFAULT_VALUES

from .kitsu import Kitsu

from .kitsu.init_pairing import init_pairing, InitPairingRequest
from .kitsu.pairing_list import get_pairing_list, PairingItemModel
from .kitsu.sync import sync_entities, SyncEntitiesRequestModel


#
# Events:
#
# kitsu.import
# - created when a project is imported.
# - worker enrolls to this event to perform full sync
#
# kitsu.sync
# - child event of kitsu.import, actuall sync should be performed here
# - when restarted, it is an equivalent to full-sync request.
#
# kitsu.event
# - when an event is received from Kitsu
# - use "sequential"
#
# kitsu.proc
# - child event of kitsu.event, processing of the event
#


class KitsuAddon(BaseServerAddon):
    name = "kitsu"
    title = "Kitsu"
    version = __version__
    settings_model: Type[KitsuSettings] = KitsuSettings
    frontend_scopes = {"settings": {}}
    services = {}

    kitsu: Kitsu | None = None

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_VALUES)

    #
    # Initialization
    #

    def initialize(self):
        self.add_endpoint("/pairing", self.list_pairings, method="GET")
        self.add_endpoint("/pairing", self.init_pairing, method="POST")
        self.add_endpoint("/sync", self.sync, method="POST")

    async def setup(self):
        pass

    #
    # Endpoints
    #

    async def sync(
        self,
        user: CurrentUser,
        # background_tasks: BackgroundTasks,
        payload: SyncEntitiesRequestModel,
    ):
        if not user.is_manager:
            raise ForbiddenException("Only managers can sync Kitsu projects")
        await sync_entities(
            self,
            user=user,
            # background_tasks=background_tasks,
            payload=payload,
        )

    async def list_pairings(self) -> list[PairingItemModel]:
        await self.ensure_kitsu()
        return await get_pairing_list(self)

    async def init_pairing(
        self,
        user: CurrentUser,
        request: InitPairingRequest,
    ) -> EmptyResponse:
        if not user.is_manager:
            raise ForbiddenException("Only managers can pair Kitsu projects")
        await self.ensure_kitsu()
        await init_pairing(self, user, request)
        return EmptyResponse(status_code=201)

    #
    # Helpers
    #

    async def ensure_kitsu(self):
        if self.kitsu is not None:
            return

        settings = await self.get_studio_settings()
        if not settings.server:
            raise InvalidSettingsException("Kitsu server is not set")

        actual_email = await Secrets.get(settings.login_email)
        actual_password = await Secrets.get(settings.login_password)

        if not actual_email:
            raise InvalidSettingsException("Kitsu email secret is not set")

        if not actual_password:
            raise InvalidSettingsException("Kitsu password secret is not set")

        self.kitsu = Kitsu(settings.server, actual_email, actual_password)

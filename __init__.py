from typing import Type

from ayon_server.addons import BaseServerAddon
from ayon_server.api.dependecies import CurrentUser
from ayon_server.api.responses import EmptyResponse
from ayon_server.exceptions import InvalidSettingsException, ForbiddenException
from ayon_server.secrets import Secrets

from .version import __version__
from .settings import KitsuSettings, DEFAULT_VALUES

from .kitsu import Kitsu
from .init_pairing import init_pairing, InitPairingRequest
from .kitsu.pairing_list import get_pairing_list, PairingItemModel


#
# Events
# kitsu.sync_request 
# - when a sync request is received, worker enrolls to this event to perform full sync
#
# kitsu.sync 
# - child event of kitsu.sync_request, actuall sync should be performed here
#
# kitsu.event 
# - when an event is received from Kitsu
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
        self.add_endpoint("/pairing", self.pairing, methods=["GET"])
        self.add_endpoint("/init", self.init_pairing, methods=["POST"])
        self.add_endpoint("/sync/{kitsu_id}", self.sync, methods=["POST"])

    async def setup(self):
        pass

    #
    # Endpoints
    #

    async def pairing(self) -> list[PairingItemModel]:
        await self.ensure_kitsu()
        return await get_pairing_list(self)

    async def sync(self, kitsu_id: str):
        await self.ensure_kitsu()

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

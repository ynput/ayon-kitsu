from typing import Type

# from fastapi import BackgroundTasks

try:
    from ayon_server.addons import BaseServerAddon
    from ayon_server.api.dependencies import CurrentUser
    from ayon_server.api.responses import EmptyResponse
    from ayon_server.exceptions import InvalidSettingsException, ForbiddenException
    from ayon_server.secrets import Secrets
    from ayon_server.entities import FolderEntity, TaskEntity
except:
    pass

from .version import __version__
from .settings import KitsuSettings, DEFAULT_VALUES

from .kitsu import Kitsu
from .kitsu import KitsuMock

from .kitsu.init_pairing import init_pairing, InitPairingRequest, sync_request
from .kitsu.pairing_list import get_pairing_list, PairingItemModel
from .kitsu.push import push_entities, PushEntitiesRequestModel
from .kitsu import utils


#
# Events:
#
# kitsu.sync_request
# - created when a project is imported.
# - worker enrolls to this event to perform full sync
#


class KitsuAddon(BaseServerAddon):
    name = "kitsu"
    title = "Kitsu"
    version = __version__
    settings_model: Type[KitsuSettings] = KitsuSettings
    frontend_scopes = {"settings": {}}
    services = {
        "processor": {"image": f"ynput/ayon-kitsu-processor:{__version__}"}
    }

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
        self.add_endpoint("/sync/{project_name}", self.sync, method="POST")
        self.add_endpoint("/push", self.push, method="POST")

    async def setup(self):
        pass

    #
    # Endpoints
    #

    async def sync(self, user: CurrentUser, project_name: str) -> EmptyResponse:
        await sync_request(project_name, user)

    async def push(
        self,
        user: CurrentUser,
        payload: PushEntitiesRequestModel,
    ):
        if not user.is_manager:
            raise ForbiddenException("Only managers can sync Kitsu projects")
        return await push_entities(
            self,
            user=user,
            payload=payload,
        )

    async def list_pairings(self, mock=False) -> list[PairingItemModel]: 
        await self.ensure_kitsu(mock)
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

    async def ensure_kitsu(self, mock=False):
        if self.kitsu is not None:
            return
        
        if mock == "True":
            self.kitsu = KitsuMock()
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

from typing import Type

from nxtools import logging

from ayon_server.addons import BaseServerAddon
from ayon_server.api.dependencies import CurrentUser
from ayon_server.api.responses import EmptyResponse
from ayon_server.exceptions import ForbiddenException, InvalidSettingsException
from ayon_server.secrets import Secrets

from .kitsu import Kitsu, KitsuMock
from .kitsu.init_pairing import InitPairingRequest, init_pairing, sync_request
from .kitsu.pairing_list import PairingItemModel, get_pairing_list
from .kitsu.push import (
    PushEntitiesRequestModel,
    RemoveEntitiesRequestModel,
    push_entities,
    remove_entities,
)
from .settings import DEFAULT_VALUES, KitsuSettings

#
# Events:
#
# kitsu.sync_request
# - created when a project is imported.
# - worker enrolls to this event to perform full sync
#


class KitsuAddon(BaseServerAddon):
    settings_model: Type[KitsuSettings] = KitsuSettings
    frontend_scopes = {
        "settings": {},
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
        self.add_endpoint("/remove", self.remove, method="POST")

    async def setup(self):
        pass

    #
    # Endpoints
    #

    async def sync(
        self, user: CurrentUser, project_name: str
    ) -> EmptyResponse:
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

    async def remove(
        self,
        user: CurrentUser,
        payload: RemoveEntitiesRequestModel,
    ):
        logging.info(f"payload: {str(payload)}")
        if not user.is_manager:
            raise ForbiddenException("Only managers can sync Kitsu projects")
        return await remove_entities(
            self,
            user=user,
            payload=payload,
        )

    async def list_pairings(
        self, mock: bool = False
    ) -> list[PairingItemModel]:
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
    async def ensure_kitsu(self, mock: bool = False):
        if self.kitsu is not None:
            return

        if mock is True:
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

import json
import logging
from ayon_server.addons import BaseServerAddon
from .settings import KitsuSettings, DEFAULT_VALUES
from ayon_server.api.dependencies import CurrentUser
from .pushing.pushing import push_entities, PushEntitiesRequestModel
from .pushing.init_pairing import init_pairing, InitPairingRequest
from ayon_server.exceptions import ForbiddenException, InvalidSettingsException
from .version import __version__
from ayon_server.secrets import Secrets
from typing import Type
from .pushing.kitsu import Kitsu

class KitsuAddon(BaseServerAddon):
    name = "kitsu"
    title = "Kitsu"
    version = __version__
    settings_model: Type[KitsuSettings] = KitsuSettings
    # frontend_scopes = {"settings": {}}
    services = {
        "Initializer": {"image": f"agamal17/kitsu-initializer:1.0"}
    }

    kitsu: Kitsu | None = None

    async def get_default_settings(self):
        settings_model_cls = self.get_settings_model()
        return settings_model_cls(**DEFAULT_VALUES)

    #
    # Initialization
    #

    def initialize(self):
        self.add_endpoint("/push", self.push, method="POST")
        self.add_endpoint("/pair", self.pair, method="POST")

    async def setup(self):
        pass

    async def pair(
            self,
            user: CurrentUser,
            request,
    ):
        request = json.loads(request)
        await self.ensure_kitsu()
        await init_pairing(
            self,
            user,
            request
        )
        
    async def push(
        self,
        user: CurrentUser,
        payload: PushEntitiesRequestModel,
    ):
        if not user.is_manager:
            raise ForbiddenException("Only managers can sync Kitsu projects")
        await push_entities(
            self,
            user=user,
            payload=payload,
        )

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

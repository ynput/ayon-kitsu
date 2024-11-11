from ayon_server.settings import BaseSettingsModel, SettingsField
from ayon_server.settings.enum import secrets_enum

from .sync_settings import SyncSettings, SYNC_DEFAULT_VALUES
from .publish_plugins import PublishPlugins, PUBLISH_DEFAULT_VALUES
from .app_start import AppStartStatusChange, APPSTART_DEFAULT_VALUES


## Entities naming pattern
#
class EntityPattern(BaseSettingsModel):
    episode: str = SettingsField(title="Episode")
    sequence: str = SettingsField(title="Sequence")
    shot: str = SettingsField(title="Shot")


class KitsuSettings(BaseSettingsModel):
    #
    ## Root fields
    #
    enabled: bool = SettingsField(True, title="Enabled")
    server: str = SettingsField(
        "",
        title="Kitsu Server",
        scope=["studio"],
    )
    login_email: str = SettingsField(
        "kitsu_email",
        enum_resolver=secrets_enum,
        title="Kitsu user email",
        scope=["studio"],
    )
    login_password: str | None = SettingsField(
        "kitsu_password",
        enum_resolver=secrets_enum,
        title="Kitsu user password",
        scope=["studio"],
    )

    #
    ## Sub entities
    #
    entities_naming_pattern: EntityPattern = SettingsField(
        default_factory=EntityPattern,
        title="Entities naming pattern",
    )
    appstart: AppStartStatusChange = SettingsField(
        default_factory=AppStartStatusChange,
        title="App start status change",
    )
    publish: PublishPlugins = SettingsField(
        default_factory=PublishPlugins,
        title="Publish plugins",
    )
    sync_settings: SyncSettings = SettingsField(
        default_factory=SyncSettings,
        title="Sync settings",
    )


DEFAULT_VALUES = {
    "entities_naming_pattern": {
        "episode": "E##",
        "sequence": "SQ##",
        "shot": "SH##",
    },
    "appstart": APPSTART_DEFAULT_VALUES,
    "publish": PUBLISH_DEFAULT_VALUES,
    "sync_settings": SYNC_DEFAULT_VALUES,
}

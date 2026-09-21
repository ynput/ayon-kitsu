from ayon_server.settings import BaseSettingsModel, SettingsField
from ayon_server.settings.enum import secrets_enum

from .sync_settings import SyncSettings, SYNC_DEFAULT_VALUES
from .publish_plugins import PublishPlugins, PUBLISH_DEFAULT_VALUES


class KitsuSettings(BaseSettingsModel):
    #
    ## Root fields
    #
    enabled: bool = SettingsField(True, title="Enabled")
    server: str = SettingsField(
        "",
        title="Kitsu Server",
        description=(
            "URL of the Kitsu instance, e.g. 'https://kitsu.mystudio.com'."
            " The '/api' suffix is appended automatically."
        ),
        scope=["studio"],
    )
    login_email: str = SettingsField(
        "kitsu_email",
        enum_resolver=secrets_enum,
        title="Kitsu user email",
        description=(
            "AYON secret holding the email of the Kitsu account the addon"
            " uses to synchronize projects and users."
        ),
        scope=["studio"],
    )
    login_password: str | None = SettingsField(
        "kitsu_password",
        enum_resolver=secrets_enum,
        title="Kitsu user password",
        description=(
            "AYON secret holding the password of that same Kitsu account."
        ),
        scope=["studio"],
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
    "publish": PUBLISH_DEFAULT_VALUES,
    "sync_settings": SYNC_DEFAULT_VALUES,
}

"""Kitsu addon."""

import os

from ayon_core.addon import (
    AYONAddon,
    IPluginPaths,
    ITrayAction,
)
from .version import __version__

KITSU_ROOT = os.path.dirname(os.path.abspath(__file__))


class KitsuAddon(AYONAddon, IPluginPaths, ITrayAction):
    """Kitsu addon class."""

    label = "Kitsu Connect"
    name = "kitsu"
    version = __version__

    def initialize(self, settings):
        """Initialization of addon."""

        kitsu_settings = settings["kitsu"]
        # Add API URL schema
        kitsu_url = kitsu_settings["server"].strip()
        if kitsu_url:
            # Ensure web url
            if not kitsu_url.startswith("http"):
                kitsu_url = f"https://{kitsu_url}"

            kitsu_url = kitsu_url.rstrip("/")

            # Check for "/api" url validity
            if not kitsu_url.endswith("api"):
                kitsu_url = f"{kitsu_url}/api"

        self.server_url = kitsu_url

        # UI which must not be created at this time
        self._dialog = None

    def tray_init(self):
        """Tray init."""

        pass

    def tray_start(self):
        """Tray start."""
        from .credentials import (
            load_credentials,
            validate_credentials,
            set_credentials_envs,
        )

        login, password = load_credentials()

        if login is None or password is None:
            # TODO raise correct type
            raise

        # Check credentials, ask them if needed
        if validate_credentials(login, password):
            set_credentials_envs(login, password)
        else:
            self.show_dialog()

    def get_global_environments(self):
        """Kitsu's global environments."""
        return {"KITSU_SERVER": self.server_url}

    def _get_dialog(self):
        if self._dialog is None:
            from .kitsu_widgets import KitsuPasswordDialog

            self._dialog = KitsuPasswordDialog()

        return self._dialog

    def show_dialog(self):
        """Show dialog to log-in."""

        # Make sure dialog is created
        dialog = self._get_dialog()

        # Show dialog
        dialog.open()

    def on_action_trigger(self):
        """Implementation of abstract method for `ITrayAction`."""
        self.show_dialog()

    def get_plugin_paths(self):
        """Implementation of abstract method for `IPluginPaths`."""

        return {
            "publish": self.get_publish_plugin_paths(),
            "hooks": self.get_launch_hook_paths(),
            # The laucher action is not working since AYON conversion
            # "actions": [os.path.join(KITSU_ROOT, "plugins", "launcher")],
        }

    def get_publish_plugin_paths(self, host_name=None):
        return [os.path.join(KITSU_ROOT, "plugins", "publish")]
    def get_launch_hook_paths(self, host_name=None):
        return [os.path.join(KITSU_ROOT, "hooks")]

def is_kitsu_enabled_in_settings(project_settings):
    """Check if kitsu is enabled in kitsu project settings.

    This function expect settings for a specific project. It is not checking
    if kitsu is enabled in general.

    Project settings gives option to disable kitsu integration per project.
    That should disable most of kitsu integration functionality, especially
    pipeline integration > publish plugins, and some automations like event
    server handlers.

    Args:
        project_settings (dict[str, Any]): Project settings.

    Returns:
        bool: True if kitsu is enabled in project settings.
    """

    kitsu_enabled = project_settings.get("enabled")
    # If 'kitsu_enabled' is not set, we assume it is enabled.
    # - this is for backwards compatibility - remove in future
    if kitsu_enabled is None:
        return True
    return kitsu_enabled

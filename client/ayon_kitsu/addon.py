"""Kitsu module."""

import os

from openpype.modules import (
    AYONAddon,
    IPluginPaths,
    ITrayAction,
)

KITSU_ROOT = os.path.dirname(os.path.abspath(__file__))


class KitsuAddon(AYONAddon, IPluginPaths, ITrayAction):
    """Kitsu module class."""

    label = "Kitsu Connect"
    name = "kitsu"

    def initialize(self, settings):
        """Initialization of module."""

        kitsu_settings = settings["kitsu"]
        # Add API URL schema
        kitsu_url = kitsu_settings["server"].strip()
        if kitsu_url:
            # Ensure web url
            if not kitsu_url.startswith("http"):
                kitsu_url = "https://" + kitsu_url

            # Check for "/api" url validity
            if not kitsu_url.endswith("api"):
                kitsu_url = "{}{}api".format(
                    kitsu_url, "" if kitsu_url.endswith("/") else "/"
                )

        self.enabled = True
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

        # Check credentials, ask them if needed
        if validate_credentials(login, password):
            set_credentials_envs(login, password)
        else:
            self.show_dialog()

    def get_global_environments(self):
        """Kitsu's global environments."""
        return {
            "KITSU_SERVER": self.server_url
        }

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
            "actions": [os.path.join(KITSU_ROOT, "plugins", "launcher")],
        }

    def get_publish_plugin_paths(self, host_name=None):
        return [os.path.join(KITSU_ROOT, "plugins", "publish")]

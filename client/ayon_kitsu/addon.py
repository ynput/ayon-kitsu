"""Kitsu module."""

import os

from openpype.modules import (
    OpenPypeModule,
    IPluginPaths,
    ITrayAction,
)

KITSU_ROOT = os.path.dirname(os.path.abspath(__file__))


class KitsuAddon(OpenPypeModule, IPluginPaths, ITrayAction):
    """Kitsu module class."""

    label = "Kitsu Connect"
    name = "kitsu"

    def initialize(self, settings):
        """Initialization of module."""
        module_settings = settings[self.name]

        # Add API URL schema
        kitsu_url = module_settings["server"].strip()
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

        self._create_dialog()

    def tray_start(self):
        """Tray start."""
        from .utils.credentials import (
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
        return {"KITSU_SERVER": self.server_url}

    def _create_dialog(self):
        # Don't recreate dialog if already exists
        if self._dialog is not None:
            return

        from .kitsu_widgets import KitsuPasswordDialog

        self._dialog = KitsuPasswordDialog()

    def show_dialog(self):
        """Show dialog to log-in."""

        # Make sure dialog is created
        self._create_dialog()

        # Show dialog
        self._dialog.open()

    def on_action_trigger(self):
        """Implementation of abstract method for `ITrayAction`."""
        self.show_dialog()

    def get_plugin_paths(self):
        """Implementation of abstract method for `IPluginPaths`."""

        return {
            "publish": self.get_publish_plugin_paths(),
            "actions": [os.path.join(KITSU_ROOT, "plugins", "launcher")],
        }

    def get_publish_plugin_paths(self, host_name):
        return [os.path.join(KITSU_ROOT, "plugins", "publish")]

from .fullsync import full_sync, full_update, full_delete
import gazu
import os
import ayon_api

class Listener:
    """Host Kitsu listener."""

    def __init__(self, login, password):
        """Create client and add listeners to events without starting it.

        Args:
            login (str): Kitsu user login
            password (str): Kitsu user password

        """
        self.settings = ayon_api.get_service_addon_settings()
        self.kitsu_server_url = self.settings.get("server").rstrip("/") + "/api"
        email_sercret = self.settings.get("login_email")
        password_secret = self.settings.get("login_password")
        self.kitsu_login_email = ayon_api.get_secret(email_sercret)["value"]
        self.kitsu_login_password = ayon_api.get_secret(password_secret)[
            "value"
        ]

        gazu.client.set_host(self.kitsu_server_url)
        gazu.set_host(self.kitsu_server_url)
        gazu.log_in(self.kitsu_login_email, self.kitsu_login_password)

        gazu.set_event_host(
            self.kitsu_server_url.replace("api", "socket.io")
        )
        self.event_client = gazu.events.init()

        gazu.events.add_listener(
            self.event_client, "project:new", full_sync
        )
        gazu.events.add_listener(
            self.event_client, "project:update", full_update
        )
        gazu.events.add_listener(
            self.event_client, "project:delete", full_delete
        )

        gazu.events.add_listener(
            self.event_client, "asset:new", full_sync
        )
        gazu.events.add_listener(
            self.event_client, "asset:update", full_update
        )
        gazu.events.add_listener(
            self.event_client, "asset:delete", full_delete
        )

        gazu.events.add_listener(
            self.event_client, "episode:new", full_sync
        )
        gazu.events.add_listener(
            self.event_client, "episode:update", full_update
        )
        gazu.events.add_listener(
            self.event_client, "episode:delete", full_delete
        )

        gazu.events.add_listener(
            self.event_client, "sequence:new", full_sync
        )
        gazu.events.add_listener(
            self.event_client, "sequence:update", full_update
        )
        gazu.events.add_listener(
            self.event_client, "sequence:delete", full_delete
        )

        gazu.events.add_listener(
            self.event_client, "shot:new", full_sync
        )
        gazu.events.add_listener(
            self.event_client, "shot:update", full_update
        )
        gazu.events.add_listener(
            self.event_client, "shot:delete", full_delete
        )

        gazu.events.add_listener(
            self.event_client, "task:new", full_sync
        )
        gazu.events.add_listener(
            self.event_client, "task:update", full_update
        )
        gazu.events.add_listener(
            self.event_client, "task:delete", full_delete
        )

        """Start listening for events."""

        gazu.events.run_client(self.event_client)


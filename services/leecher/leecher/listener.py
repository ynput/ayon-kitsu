"""
A Kitsu Events listener leecher for Ayon.

This service will continually run and listen for any Gazu events
Kitsu and converts them to Ayon events, and can be configured from the Ayon
Addon settings page.
"""

import inspect
import os
import socket
import sys
import time
from typing import Any

import ayon_api
import gazu
from kitsu_common.utils import (
    KitsuServerError,
    create_short_name,
    get_kitsu_credentials,
)
from nxtools import log_traceback, logging, slugify

if service_name := os.environ.get("AYON_SERVICE_NAME"):
    logging.user = service_name


class KitsuListener:
    """Host Kitsu listener."""

    def __init__(self):
        #
        # Connect to Ayon
        #

        try:
            ayon_api.init_service()
            connected = True
        except Exception:
            log_traceback()
            connected = False

        if not connected:
            print("Kitsu Leecher failed to connect to Ayon")
            # Sleep for 10 seconds, so it is possible to see the message in
            #   docker
            # NOTE: Becuase AYON connection failed, there's no way how to log it
            #   to AYON server (obviously)... So stdout is all we have.
            time.sleep(10)
            sys.exit(1)

        #
        # Load settings and stuff...
        #

        self.addon_name = ayon_api.get_service_addon_name()
        self.addon_version = ayon_api.get_service_addon_version()
        self.settings = ayon_api.get_service_addon_settings()
        self.entrypoint = f"/addons/{self.addon_name}/{self.addon_version}"
        self.kitsu_server_url, self.kitsu_login_email, self.kitsu_login_password = (
            get_kitsu_credentials(ayon_api, self.settings)
        )

        #
        # Connect to Kitsu
        #

        gazu.set_host(self.kitsu_server_url)
        if not gazu.client.host_is_valid():
            raise KitsuServerError(
                f"Kitsu server `{self.kitsu_server_url}` is not valid"
            )

        try:
            gazu.log_in(self.kitsu_login_email, self.kitsu_login_password)
        except gazu.exception.AuthFailedException as e:
            raise KitsuServerError(f"Kitsu login failed: {e}") from e

        #
        # Set all listeners
        #

        self.set_listeners()

    def set_listeners(self):
        logging.info("Initializing the Kitsu Listeners.")

        gazu.set_event_host(self.kitsu_server_url.replace("/api", ""))
        self.event_client = gazu.events.init()

        gazu.events.add_listener(self.event_client, "project:new", self._new_project)
        gazu.events.add_listener(
            self.event_client, "project:update", self._update_project
        )
        gazu.events.add_listener(
            self.event_client, "project:delete", self._delete_project
        )

        gazu.events.add_listener(self.event_client, "asset:new", self._new_asset)
        gazu.events.add_listener(self.event_client, "asset:update", self._update_asset)
        gazu.events.add_listener(self.event_client, "asset:delete", self._delete_asset)

        gazu.events.add_listener(self.event_client, "episode:new", self._new_episode)
        gazu.events.add_listener(
            self.event_client, "episode:update", self._update_episode
        )
        gazu.events.add_listener(
            self.event_client, "episode:delete", self._delete_episode
        )

        gazu.events.add_listener(self.event_client, "sequence:new", self._new_sequence)
        gazu.events.add_listener(
            self.event_client, "sequence:update", self._update_sequence
        )
        gazu.events.add_listener(
            self.event_client, "sequence:delete", self._delete_sequence
        )

        gazu.events.add_listener(self.event_client, "shot:new", self._new_shot)
        gazu.events.add_listener(self.event_client, "shot:update", self._update_shot)
        gazu.events.add_listener(self.event_client, "shot:delete", self._delete_shot)

        gazu.events.add_listener(self.event_client, "task:new", self._new_task)
        gazu.events.add_listener(self.event_client, "task:update", self._update_task)
        gazu.events.add_listener(self.event_client, "task:delete", self._delete_task)
        gazu.events.add_listener(self.event_client, "task:assign", self._assign_task)
        gazu.events.add_listener(
            self.event_client, "task:unassign", self._unassign_task
        )
        gazu.events.add_listener(
            self.event_client, "task:status-changed", self._status_changed_task
        )

        gazu.events.add_listener(self.event_client, "edit:new", self._new_edit)
        gazu.events.add_listener(self.event_client, "edit:update", self._update_edit)
        gazu.events.add_listener(self.event_client, "edit:delete", self._delete_edit)

    def start_listening(self):
        """Start listening for events."""
        logging.info("Listening to Kitsu events...")
        gazu.events.run_client(self.event_client)

    def get_ep_dict(self, ep_id):
        print(inspect.stack()[0][3])
        return
        if ep_id and ep_id != "":
            return gazu.entity.get_entity(ep_id)
        return

    # == Project ==
    def _new_project(self, data):
        data["event_type"] = "project:new"
        self.send_kitsu_event_to_ayon(data, event_type="sync-from-kitsu")

    def _update_project(self, data):
        data["event_type"] = "project:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_project(self, data):
        data["event_type"] = "project:delete"
        self.send_kitsu_event_to_ayon(data)

    # == Asset ==
    def _new_asset(self, data):
        data["event_type"] = "asset:new"
        self.send_kitsu_event_to_ayon(data)

    def _update_asset(self, data):
        data["event_type"] = "asset:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_asset(self, data):
        data["event_type"] = "asset:delete"
        self.send_kitsu_event_to_ayon(data)

    # == Episode ==
    def _new_episode(self, data):
        data["event_type"] = "episode:new"
        self.send_kitsu_event_to_ayon(data)

    def _update_episode(self, data):
        data["event_type"] = "episode:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_episode(self, data):
        data["event_type"] = "episode:delete"
        self.send_kitsu_event_to_ayon(data)

    # == Sequence ==
    def _new_sequence(self, data):
        data["event_type"] = "sequence:new"
        self.send_kitsu_event_to_ayon(data)

    def _update_sequence(self, data):
        data["event_type"] = "sequence:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_sequence(self, data):
        data["event_type"] = "sequence:delete"
        self.send_kitsu_event_to_ayon(data)

    # == Shot ==
    def _new_shot(self, data):
        data["event_type"] = "shot:new"
        self.send_kitsu_event_to_ayon(data)

    def _update_shot(self, data):
        data["event_type"] = "shot:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_shot(self, data):
        data["event_type"] = "shot:delete"
        self.send_kitsu_event_to_ayon(data)

    # == Task ==
    def _new_task(self, data):
        data["event_type"] = "task:new"
        self.send_kitsu_event_to_ayon(data)

    def _update_task(self, data):
        data["event_type"] = "task:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_task(self, data):
        data["event_type"] = "task:delete"
        self.send_kitsu_event_to_ayon(data)

    def _assign_task(self, data):
        data["event_type"] = "task:assign"
        self.send_kitsu_event_to_ayon(data)

    def _unassign_task(self, data):
        data["event_type"] = "task:unassign"
        self.send_kitsu_event_to_ayon(data)

    def _status_changed_task(self, data):
        data["event_type"] = "task:status-changed"
        self.send_kitsu_event_to_ayon(data)

    # == Edit ==
    def _new_edit(self, data):
        data["event_type"] = "edit:new"
        self.send_kitsu_event_to_ayon(data)

    def _update_edit(self, data):
        data["event_type"] = "edit:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_edit(self, data):
        data["event_type"] = "edit:delete"
        self.send_kitsu_event_to_ayon(data)

    def send_kitsu_event_to_ayon(
        self, payload: dict[str, Any], event_type: str = "kitsu-event"
    ):
        """Send the Kitsu event as an Ayon event.

        Args:
            payload (dict): The Event data.
        """

        logging.info(f"Processing Kitsu Event {payload}")
        description = f"Leeched '{payload['event_type']}' as a '{event_type}' event"
        logging.info(description)

        try:
            project_name = gazu.project.get_project(payload["project_id"])["name"]
            legal_project_name = slugify(project_name, separator="_", lower=False)
            legal_project_code = create_short_name(legal_project_name)
        except Exception:
            project_name = None
            legal_project_name = None
            legal_project_code = None

        logging.info(
            f"Event is from Project {legal_project_name} [{legal_project_code}] ({payload['project_id']})"
        )

        ayon_api.dispatch_event(
            "kitsu.event",
            sender=socket.gethostname(),
            project_name=legal_project_name,
            description=description,
            summary=None,
            payload={
                "event_type": event_type,
                "payload": payload,
                "project_name": legal_project_name,
                "project_code": legal_project_code,
            },
        )

        logging.info("Dispatched Ayon event ", payload["event_type"])

import os
import sys
import socket
import time

import ayon_api
import gazu

from nxtools import logging, log_traceback

from .fullsync import full_sync
from . import update_from_kitsu


if service_name := os.environ.get("AYON_SERVICE_NAME"):
    logging.user = service_name

SENDER = f"kitsu-processor-{socket.gethostname()}"


class KitsuServerError(Exception):
    pass


class KitsuSettingsError(Exception):
    pass


class KitsuProcessor:
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
            time.sleep(10)
            print("KitsuProcessor failed to connect to Ayon")
            sys.exit(1)

        #
        # Load settings and stuff...
        #

        self.addon_name = ayon_api.get_service_addon_name()
        self.addon_version = ayon_api.get_service_addon_version()
        self.settings = ayon_api.get_service_addon_settings()
        self.entrypoint = f"/addons/{self.addon_name}/{self.addon_version}"

        #
        # Get Kitsu server credentials from settings
        #

        try:
            self.kitsu_server_url = self.settings.get("server").rstrip("/") + "/api"

            email_sercret = self.settings.get("login_email")
            password_secret = self.settings.get("login_password")

            assert email_sercret, f"Email secret `{email_sercret}` not set"
            assert password_secret, f"Password secret `{password_secret}` not set"

            try:
                self.kitsu_login_email = ayon_api.get_secret(email_sercret)["value"]
                self.kitsu_login_password = ayon_api.get_secret(password_secret)[
                    "value"
                ]
            except KeyError as e:
                raise KitsuSettingsError(f"Secret `{e}` not found") from e

            assert self.kitsu_login_password, "Kitsu password not set"
            assert self.kitsu_server_url, "Kitsu server not set"
            assert self.kitsu_login_email, "Kitsu email not set"
        except AssertionError as e:
            logging.error(f"KitsuProcessor failed to initialize: {e}")
            raise KitsuSettingsError() from e

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
            logging.info(f"Gazu logged in as {self.kitsu_login_email}")
        except gazu.exception.AuthFailedException as e:
            raise KitsuServerError(f"Kitsu login failed: {e}") from e
        
    def add_gazu_event_listeners(self):
        
        gazu.set_event_host(
            self.kitsu_server_url.replace("api", "socket.io")
        )
        self.event_client = gazu.events.init()

        # gazu.events.add_listener(
        #     self.event_client, "project:new", self._new_project
        # )
        # gazu.events.add_listener(
        #     self.event_client, "project:update", self._update_project
        # )
        # gazu.events.add_listener(
        #     self.event_client, "project:delete", self._delete_project
        # )
    
        
        gazu.events.add_listener(
            self.event_client, 
            "asset:new", 
            self.update_asset
        )
        gazu.events.add_listener(
            self.event_client, 
            "asset:update", 
            self.update_asset
        )
        gazu.events.add_listener(
            self.event_client, 
            "asset:delete", 
            self.delete_asset
        )
        gazu.events.add_listener(
            self.event_client, 
            "episode:new", 
            lambda data: update_from_kitsu.create_or_update_episode(self, data)
        )
        gazu.events.add_listener(
            self.event_client,
            "episode:update", 
            lambda data: update_from_kitsu.create_or_update_episode(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "episode:delete", 
            lambda data: update_from_kitsu.delete_episode(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "sequence:new",
            lambda data: update_from_kitsu.create_or_update_sequence(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "sequence:update", 
            lambda data: update_from_kitsu.create_or_update_sequence(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "sequence:delete", 
            lambda data: update_from_kitsu.delete_sequence(self, data)
        )
        gazu.events.add_listener(
            self.event_client,
            "shot:new",
            lambda data: update_from_kitsu.create_or_update_shot(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "shot:update", 
            lambda data: update_from_kitsu.create_or_update_shot(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "shot:delete", 
            lambda data: update_from_kitsu.delete_shot(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "task:new", 
            lambda data: update_from_kitsu.create_or_update_task(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "task:update", 
            lambda data: update_from_kitsu.create_or_update_task(self, data)
        )
        gazu.events.add_listener(
            self.event_client, 
            "task:delete", 
            lambda data: update_from_kitsu.delete_task(self, data)
        )
        logging.info("Gazu event listeners added")

    def update_asset(self, data):
        logging.info("KitsuProcessor update_asset")
        ayon_api.init_service()
        logging.info("KitsuProcessor logged in")
        update_from_kitsu.create_or_update_asset(self, data)

    def delete_asset(self, data):
        logging.info("KitsuProcessor delete_asset")
        ayon_api.init_service()
        logging.info("KitsuProcessor logged in")
        update_from_kitsu.delete_asset(self, data)


    def start_processing(self):
        logging.info("KitsuProcessor started")
        self.add_gazu_event_listeners()
        
        while True:
            job = ayon_api.enroll_event_job(
                source_topic="kitsu.sync_request",
                target_topic="kitsu.sync",
                sender=SENDER,
                description="Syncing Kitsu to Ayon",
                max_retries=3,
            )

            if not job:
                time.sleep(5)
                continue

            src_job = ayon_api.get_event(job["dependsOn"])


            kitsu_project_id = src_job["summary"]["kitsuProjectId"]
            ayon_project_name = src_job["project"]

            ayon_api.update_event(
                job["id"],
                sender=SENDER,
                status="in_progress",
                project_name=ayon_project_name,
                description="Syncing Kitsu project...",
            )

            try:
                full_sync(self, kitsu_project_id, ayon_project_name)
            except Exception:
                log_traceback(f"Unable to sync kitsu project {ayon_project_name}")
                
                ayon_api.update_event(
                    job["id"],
                    sender=SENDER,
                    status="failed",
                    project_name=ayon_project_name,
                    description="Sync failed",
                )

            else:
                ayon_api.update_event(
                    job["id"],
                    sender=SENDER,
                    status="finished",
                    project_name=ayon_project_name,
                    description="Kitsu sync finished",
                )

        logging.info("KitsuProcessor finished processing")
        gazu.log_out()

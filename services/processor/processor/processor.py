import os
import socket
import sys
import time

import ayon_api
import gazu
from kitsu_common.utils import (
    KitsuServerError,
    KitsuSettingsError,
)
from nxtools import log_traceback, logging

from .fullsync import full_sync

if service_name := os.environ.get("AYON_SERVICE_NAME"):
    logging.user = service_name

SENDER = f"kitsu-processor-{socket.gethostname()}"


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
        except gazu.exception.AuthFailedException as e:
            raise KitsuServerError(f"Kitsu login failed: {e}") from e

    def start_processing(self):
        logging.info("KitsuProcessor started")
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

import time
import sys
import ayon_api
import gazu
from .fullsync import full_sync
from .listeners import Listener
from nxtools import logging, log_traceback
import os

if service_name := os.environ.get("AYON_SERVICE_NAME"):
    logging.user = service_name


class KitsuServerError(Exception):
    pass


class KitsuSettingsError(Exception):
    pass


class KitsuInitializer:
    def __init__(self):
        #
        # Connect to Ayon
        #

        try:
            ayon_api.init_service(addon_name='kitsu', addon_version='1.0.0', service_name='kitsu-initializer')
            connected = True
        except Exception:
            log_traceback()
            connected = False

        if not connected:
            time.sleep(10)
            print("KitsuInitializer failed to connect to Ayon")
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
            logging.error(f"KitsuInitializer failed to initialize: {e}")
            raise KitsuSettingsError() from e

        #
        # Connect to Kitsu
        #
        gazu.client.set_host(self.kitsu_server_url)
        gazu.set_host(self.kitsu_server_url)
        if not gazu.client.host_is_valid():
            raise KitsuServerError(
                f"Kitsu server `{self.kitsu_server_url}` is not valid"
            )

        gazu.log_in(self.kitsu_login_email, self.kitsu_login_password)

        logging.info("KitsuInitializer started")

        projects = gazu.project.all_projects()

        for project in projects:
            kitsu_project_id = project['id']
            try:
                full_sync(project_id = kitsu_project_id)
            except Exception:
                pass
        Listener(self.kitsu_login_email, self.kitsu_login_password)

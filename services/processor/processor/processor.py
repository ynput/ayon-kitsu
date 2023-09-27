import sys
import time


import ayon_api
import gazu

from nxtools import logging, log_traceback

from .fullsync import full_sync


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
        except gazu.exception.AuthFailedException as e:
            raise KitsuServerError(f"Kitsu login failed: {e}") from e

    def start_processing(self):
        while True:
            #
            # Get the next task
            #

            EPISODIC = ("0d49b788-d73f-4014-85d4-f84452dfce46", "Episodic")
            CGDEMO = ("736f0027-bd72-4972-9bca-08bd51d7afee", "AY_CG_Demo")
            SYNCTEST = ("4ce7834c-3056-4cb1-ae4b-2d4c94cf4303", "Sync_test")
            full_sync(self, *SYNCTEST)

            break

        logging.info("KitsuProcessor finished processing")
        gazu.log_out()

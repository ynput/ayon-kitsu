"""
A Kitsu Events listener processor for Ayon.

This service will continually run and query the Ayon Events Server in orther to
entroll the events of topic `kitsu.leech` to perform processing of Kitsu
related events.
"""

import importlib
import os
import socket
import sys
import time
import types
from typing import Any

import ayon_api
import gazu
from kitsu_common.utils import (
    KitsuServerError,
    get_kitsu_credentials,
)
from nxtools import log_traceback, logging

from .fullsync import full_sync

if service_name := os.environ.get("AYON_SERVICE_NAME"):
    logging.user = service_name


class KitsuProcessor:
    def __init__(self):
        """A class to process AYON events of `kitsu.event` topic.

        These events contain an "action" key in the payload, which is
        used to match to any handler that has REGISTER_EVENT_TYPE attribute.

        For example, the `handlers/project_sync.py` will be triggered whenever
        an event has the action "create-project", since it has the following
        constant declared `REGISTER_EVENT_TYPE = ["create-project"]`.

        New handlers can be added to the `handlers` directory and as long as they
        have `REGISTER_EVENT_TYPE` declared, if an event with said action is pending,
        it will be triggered, this directory is traversed upon initialization.

        In order for this service to work, the settings for the Addon have to be
        populated in 'AYON > Studio Settings > Kitsu'.
        """
        logging.info("Initializing the Kitsu Processor.")

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
        self.kitsu_server_url, self.kitsu_login_email, self.kitsu_login_password = (
            get_kitsu_credentials(ayon_api, self.settings)
        )

        # TODO Add polling frequency in settings
        try:
            self.kitsu_polling_frequency = int(
                self.settings["service_settings"]["polling_frequency"]
            )
        except Exception:
            self.kitsu_polling_frequency = 5

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

        self.handlers_map = self._get_handlers()
        if not self.handlers_map:
            logging.error("No handlers found for the processor, aborting.")
        else:
            logging.debug(f"Found the these handlers: {self.handlers_map}")

    def _get_handlers(self) -> dict[Any, Any]:
        """Import the handlers found in the `handlers` directory.

        Scan the `handlers` directory and build a dictionary with
        each `REGISTER_EVENT_TYPE` found in importable Python files,
        wich get stored as a list, since several handlers could be
        triggered by the same event type.
        """
        handlers_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "handlers"
        )
        handlers_dict = {}

        for root, handlers_directories, handler_files in os.walk(handlers_dir):
            for handler in handler_files:
                if handler.endswith(".py") and not handler.startswith((".", "_")):
                    module_name = str(handler.replace(".py", ""))
                    module_obj = types.ModuleType(module_name)

                    module_loader = importlib.machinery.SourceFileLoader(
                        module_name, os.path.join(root, handler)
                    )
                    module_loader.exec_module(module_obj)
                    register_event_types = module_obj.REGISTER_EVENT_TYPE

                    for event_type in register_event_types:
                        handlers_dict.setdefault(event_type, []).append(module_obj)

        return handlers_dict

    def start_processing(self):
        logging.info("KitsuProcessor started")
        while True:
            try:
                event = ayon_api.enroll_event_job(
                    source_topic="kitsu.event",
                    target_topic="kitsu.proc",
                    sender=socket.gethostname(),
                    description="Enrolling to any `kitsu.event` Event...",
                    max_retries=3,
                )

                # This is the old full sync event
                job = ayon_api.enroll_event_job(
                    source_topic="kitsu.sync_request",
                    target_topic="kitsu.sync",
                    sender=socket.gethostname(),
                    description="Syncing Kitsu to Ayon",
                    max_retries=3,
                )

                if not event and not job:
                    time.sleep(self.kitsu_polling_frequency)
                    continue

                if event:
                    source_event = ayon_api.get_event(event["dependsOn"])
                    payload = source_event["payload"]

                    if not payload:
                        time.sleep(self.kitsu_polling_frequency)
                        ayon_api.update_event(
                            event["id"],
                            description=f"Unable to process the event <{source_event['id']}> since it has no Kitsu Payload!",
                            status="finished",
                        )
                        ayon_api.update_event(source_event["id"], status="finished")
                        continue

                    for handler in self.handlers_map.get(payload["event_type"], []):
                        # If theres any handler "subscirbed" to this event type..
                        try:
                            logging.info(f"Running the Handler {handler}")
                            ayon_api.update_event(
                                event["id"],
                                description=f"Procesing event with Handler {payload['event_type']}...",
                                status="finished",
                            )
                            handler.process_event(
                                self.kitsu_server_url,
                                self.kitsu_login_email,
                                self.kitsu_login_password,
                                **payload,
                            )

                        except Exception as e:
                            logging.error(
                                f"Unable to process handler {handler.__name__}"
                            )
                            log_traceback(e)
                            ayon_api.update_event(
                                event["id"],
                                status="failed",
                                description=f"An error ocurred while processing the Event: {e}",
                            )
                            ayon_api.update_event(
                                source_event["id"],
                                status="failed",
                                description=f"The service `processor` was unable to process this event. Check the `shotgrid.proc` <{event['id']}> event for more info.",
                            )

                    logging.info("Event has been processed... setting to finished!")
                    ayon_api.update_event(
                        event["id"],
                        description="Event processed succsefully.",
                        status="finished",
                    )
                    ayon_api.update_event(source_event["id"], status="finished")
                elif job:  # Old sync code
                    src_job = ayon_api.get_event(job["dependsOn"])
                    kitsu_project_id = src_job["summary"]["kitsuProjectId"]
                    ayon_project_name = src_job["project"]

                    ayon_api.update_event(
                        job["id"],
                        sender=socket.gethostname(),
                        status="in_progress",
                        project_name=ayon_project_name,
                        description="Syncing Kitsu project...",
                    )

                    try:
                        full_sync(self, kitsu_project_id, ayon_project_name)
                    except Exception:
                        log_traceback(
                            f"Unable to sync kitsu project {ayon_project_name}"
                        )

                        ayon_api.update_event(
                            job["id"],
                            sender=socket.gethostname(),
                            status="failed",
                            project_name=ayon_project_name,
                            description="Sync failed",
                        )

                    else:
                        ayon_api.update_event(
                            job["id"],
                            sender=socket.gethostname(),
                            status="finished",
                            project_name=ayon_project_name,
                            description="Kitsu sync finished",
                        )

            except Exception as err:
                log_traceback(err)

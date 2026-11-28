import os
import socket
import sys
import threading
import time
import traceback
from typing import Any

import ayon_api
import gazu
from nxtools import log_traceback, logging

from .fullsync import project_full_sync
from .update_from_kitsu import (
    create_or_update_asset,
    create_or_update_concept,
    create_or_update_edit,
    create_or_update_episode,
    create_or_update_person,
    create_or_update_sequence,
    create_or_update_shot,
    create_or_update_task,
    create_or_update_casting,
    delete_asset,
    delete_concept,
    delete_edit,
    delete_episode,
    delete_person,
    delete_project,
    delete_sequence,
    delete_shot,
    delete_task,
    update_project,
)

if service_name := os.environ.get("AYON_SERVICE_NAME"):
    logging.user = service_name

SENDER = f"kitsu-processor-{socket.gethostname()}"

# How often the watchdog checks the Kitsu event client's connection state.
EVENT_WATCHDOG_INTERVAL = 30
# Force a full reconnect if the event client has been disconnected for
# longer than this, rather than letting socketio retry forever with a
# potentially stale auth token.
EVENT_WATCHDOG_MAX_DISCONNECTED = 120
# Delay between reconnect attempts of the Kitsu event client.
EVENT_RECONNECT_DELAY = 10


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
        # Get list of projects that have been paired
        #
        self.pairing_list = self.get_pairing_list()

        #
        # Get Kitsu server credentials from settings
        #

        try:
            self.kitsu_server_url = (
                self.settings.get("server").rstrip("/") + "/api"
            )

            email_secret = self.settings.get("login_email")
            password_secret = self.settings.get("login_password")

            if not email_secret:
                raise ValueError(f"Email secret `{email_secret}` not set")

            if not password_secret:
                raise ValueError(
                    f"Password secret `{password_secret}` not set"
                )

            self.kitsu_login_email = self._read_kitsu_secret(
                email_secret, "email"
            )
            self.kitsu_login_password = self._read_kitsu_secret(
                password_secret, "password"
            )

            assert self.kitsu_login_password, "Kitsu password not set"
            assert self.kitsu_server_url, "Kitsu server not set"
            assert self.kitsu_login_email, "Kitsu email not set"
        except KitsuSettingsError:
            raise
        except (AssertionError, ValueError, AttributeError) as e:
            err_msg = f"KitsuProcessor failed to initialize: {e}"
            logging.error(err_msg)
            self._dispatch_service_error(err_msg)
            raise KitsuSettingsError(err_msg) from e

        #
        # Connect to Kitsu
        #
        gazu.set_host(self.kitsu_server_url)
        if not gazu.client.host_is_valid():
            err_msg = f"Kitsu server `{self.kitsu_server_url}` is not valid"
            self._dispatch_service_error(err_msg)
            raise KitsuServerError(err_msg)

        try:
            gazu.log_in(self.kitsu_login_email, self.kitsu_login_password)
            logging.info(f"Gazu logged in as {self.kitsu_login_email}")
        except gazu.exception.AuthFailedException as e:
            err_msg = f"Kitsu login failed: {e}"
            self._dispatch_service_error(err_msg)
            raise KitsuServerError(err_msg) from e

        # Zou access tokens expire after 7 days: re-login on 401 and let
        # gazu replay the failed request.
        self._relogging_in = False

        def relogin(client, path):
            if self._relogging_in:
                return False
            self._relogging_in = True
            try:
                gazu.log_in(
                    self.kitsu_login_email,
                    self.kitsu_login_password,
                    client=client,
                )
                logging.info(f"Kitsu session renewed (on {path})")
                return True
            except Exception:
                log_traceback("Kitsu re-login failed")
                return False
            finally:
                self._relogging_in = False

        gazu.client.default_client.callback_not_authenticated = relogin

        # init event client
        self.kitsu_events_url = self.kitsu_server_url.replace(
            "api", "socket.io"
        )
        gazu.set_event_host(self.kitsu_events_url)
        self.event_client = None

        # ============= Add Kitsu Event Listeners ==============
        # Connects the event client and (re)connects it
        # whenever the connection drops or the watchdog forces it.
        gazu_listener_thread = threading.Thread(
            target=self.run_gazu_listeners, daemon=True
        )
        gazu_listener_thread.start()

        # python-socketio's own reconnection logic can get stuck
        # retrying forever using a stale auth header (captured once at
        # connect time), e.g. after the Kitsu server restarts or the
        # access token expires.
        # This watchdog detects that and forces a clean reconnect.
        gazu_watchdog_thread = threading.Thread(
            target=self.watch_gazu_connection, daemon=True
        )
        gazu_watchdog_thread.start()

    def run_gazu_listeners(self):
        """(Re)connect the Kitsu event client and listen for events.

        Runs forever in its own thread. Whenever the connection is lost,
        dropped, or closed by the watchdog, this re-authenticates with Kitsu
        (in case the access token has expired) and reconnects.
        """
        while True:
            try:
                gazu.log_in(
                    self.kitsu_login_email, self.kitsu_login_password
                )
            except Exception:
                log_traceback(
                    "Failed to re-login to Kitsu before (re)connecting "
                    "the event client"
                )
                time.sleep(EVENT_RECONNECT_DELAY)
                continue

            try:
                self.event_client = gazu.events.init(ssl_verify=True)
                self.add_gazu_listeners()
                logging.info("Gazu event listeners added")
                gazu.events.run_client(self.event_client)
            except Exception:
                log_traceback("Gazu event client crashed")

            logging.warning(
                "Gazu event listener disconnected, reconnecting in "
                f"{EVENT_RECONNECT_DELAY}s..."
            )
            try:
                if self.event_client is not None:
                    self.event_client.disconnect()
            except Exception:
                pass
            time.sleep(EVENT_RECONNECT_DELAY)

    def watch_gazu_connection(self):
        """Force a full reconnect if the event client stays disconnected.

        Disconnecting here causes `run_gazu_listeners` to loop around and
        reconnect with a freshly logged-in client.
        """
        disconnected_since = None
        while True:
            time.sleep(EVENT_WATCHDOG_INTERVAL)

            connected = bool(
                self.event_client and self.event_client.connected
            )
            if connected:
                disconnected_since = None
                continue

            if disconnected_since is None:
                disconnected_since = time.time()
                continue

            if (
                time.time() - disconnected_since
                > EVENT_WATCHDOG_MAX_DISCONNECTED
            ):
                logging.warning(
                    "Kitsu event client has been disconnected for over "
                    f"{EVENT_WATCHDOG_MAX_DISCONNECTED}s, forcing "
                    "reconnect"
                )
                try:
                    self.event_client.disconnect()
                except Exception:
                    log_traceback()
                disconnected_since = None

    def _read_kitsu_secret(self, secret_name: str, label: str) -> str:
        """Fetch a named AYON secret and report lookup failures to AYON.

        Args:
            secret_name: Secret key configured in Kitsu addon settings.
            label: Human-readable role of the secret (e.g. ``email``).

        Returns:
            Secret string value.

        Raises:
            KitsuSettingsError: When the secret cannot be fetched or is empty.
        """
        client = getattr(self, "ayon_api", ayon_api)
        try:
            secret = client.get_secret(secret_name)
            value = secret["value"] if isinstance(secret, dict) else None
        except Exception as exc:
            err_msg = (
                f"Unable to read Kitsu {label} secret `{secret_name}`: {exc}"
            )
            logging.error(err_msg)
            self._dispatch_service_error(err_msg)
            raise KitsuSettingsError(err_msg) from exc

        if not value:
            err_msg = (
                f"Kitsu {label} secret `{secret_name}` is missing or empty"
            )
            logging.error(err_msg)
            self._dispatch_service_error(err_msg)
            raise KitsuSettingsError(err_msg)
        return value

    def _extract_event_id(self, res: Any) -> str | None:
        """Extract an AYON event ID from a ``dispatch_event`` response.

        Args:
            res: Response returned by ``ayon_api.dispatch_event``.

        Returns:
            Event ID string when present, else None.
        """
        if isinstance(res, str):
            return res
        if isinstance(res, dict):
            return res.get("id")
        res_data = getattr(res, "data", None)
        if isinstance(res_data, dict):
            return res_data.get("id")
        if isinstance(res_data, str):
            return res_data
        return None

    def _redact_error_text(self, text: str) -> str:
        """Strip configured Kitsu credentials from error text before storing.

        Args:
            text: Raw error message or traceback.

        Returns:
            Redacted error string safe for AYON events and logs.
        """
        if not text:
            return text
        secrets = [
            str(val)
            for attr in ("kitsu_login_password", "kitsu_login_email")
            if (val := getattr(self, attr, None))
        ]
        cleaned = text
        for secret in sorted(set(secrets), key=len, reverse=True):
            cleaned = cleaned.replace(secret, "[REDACTED]")
        return cleaned

    def _dispatch_service_error(
        self,
        message: str,
        traceback_text: str | None = None,
        project_name: str | None = None,
    ) -> None:
        """Dispatch a ``log.error`` event to AYON for service-level errors.

        Args:
            message: Human-readable failure summary.
            traceback_text: Optional formatted traceback.
            project_name: Optional AYON project name associated with the error.
        """
        client = getattr(self, "ayon_api", ayon_api)
        if not hasattr(client, "dispatch_event"):
            return
        safe_msg = self._redact_error_text(message)
        payload: dict[str, Any] = {"message": safe_msg, "error": safe_msg}
        if traceback_text:
            payload["traceback"] = self._redact_error_text(traceback_text)
        try:
            client.dispatch_event(
                "log.error",
                sender=SENDER,
                project_name=project_name,
                description="Kitsu processor error",
                payload=payload,
                finished=True,
                store=True,
            )
        except Exception:
            log_traceback("Unable to dispatch Kitsu processor log.error event")

    def _dispatch_inbound_error(
        self,
        event_name: str,
        data: Any,
        exc: BaseException,
        traceback_text: str,
    ) -> None:
        """Record a failed inbound Kitsu event in AYON ``/events``.

        Args:
            event_name: Kitsu Socket.IO event name (e.g. ``shot:update``).
            data: Incoming event data dictionary.
            exc: Raised exception.
            traceback_text: Formatted traceback string.
        """
        client = getattr(self, "ayon_api", ayon_api)
        if not hasattr(client, "dispatch_event"):
            return
        project_name = None
        if isinstance(data, dict) and data.get("project_id"):
            project_name = self.get_paired_ayon_project(data["project_id"])
        error_text = self._redact_error_text(str(exc) or type(exc).__name__)
        safe_tb = self._redact_error_text(traceback_text)
        short_err = (
            error_text[:200] + "..." if len(error_text) > 200 else error_text
        )
        description = f"Inbound {event_name} failed: {short_err}"
        payload = {
            "event": event_name,
            "error": error_text,
            "message": safe_tb,
        }
        try:
            res = client.dispatch_event(
                "kitsu.inbound_sync",
                sender=SENDER,
                project_name=project_name,
                description=description,
                payload=payload,
                finished=False,
                store=True,
            )
            event_id = self._extract_event_id(res)
            if event_id and hasattr(client, "update_event"):
                client.update_event(
                    event_id,
                    sender=SENDER,
                    project_name=project_name,
                    status="failed",
                    description=description,
                    payload=payload,
                )
        except Exception:
            log_traceback(
                f"Unable to record kitsu.inbound_sync error for {event_name}"
            )

    def _run_inbound_handler(
        self, event_name: str, handler: Any, data: Any
    ) -> Any:
        """Execute an inbound Kitsu listener and report errors to AYON.

        Args:
            event_name: Kitsu Socket.IO event name.
            handler: Callable accepting ``(processor, data)``.
            data: Kitsu event payload dict.

        Returns:
            Handler return value on success, or ``None`` on failure.
        """
        event_data = dict(data) if isinstance(data, dict) else data
        try:
            result = handler(self, event_data)
            if result is not None:
                status_code = getattr(result, "status_code", None)
                if isinstance(status_code, int) and status_code >= 400:
                    detail = (
                        getattr(result, "detail", None)
                        or getattr(result, "text", None)
                        or ""
                    )
                    suffix = f": {detail}" if detail else ""
                    raise RuntimeError(
                        f"AYON push failed with HTTP {status_code}{suffix}"
                    )
            return result
        except Exception as exc:
            tb_text = traceback.format_exc()
            log_traceback(f"Inbound Kitsu event '{event_name}' failed")
            self._dispatch_inbound_error(event_name, event_data, exc, tb_text)
            return None

    def add_gazu_listeners(self):
        listeners = [
            ("project:update", update_project),
            ("project:delete", delete_project),
            ("asset:new", create_or_update_asset),
            ("asset:update", create_or_update_asset),
            ("asset:delete", delete_asset),
            ("episode:new", create_or_update_episode),
            ("episode:update", create_or_update_episode),
            ("episode:delete", delete_episode),
            ("sequence:new", create_or_update_sequence),
            ("sequence:update", create_or_update_sequence),
            ("sequence:delete", delete_sequence),
            ("shot:new", create_or_update_shot),
            ("shot:update", create_or_update_shot),
            ("shot:casting-update", create_or_update_casting),
            ("asset:casting-update", create_or_update_casting),
            ("shot:delete", delete_shot),
            ("task:new", create_or_update_task),
            ("task:update", create_or_update_task),
            ("task:delete", delete_task),
            ("edit:new", create_or_update_edit),
            ("edit:update", create_or_update_edit),
            ("edit:delete", delete_edit),
            ("person:new", create_or_update_person),
            ("person:update", create_or_update_person),
            ("person:delete", delete_person),
        ]
        # Concept events were fixed in Zou 0.19.0, so listen only if
        # the user is running Zou equal or above 0.19.0
        if tuple(gazu.client.get_api_version().split(".")) >= ("0", "19", "0"):
            listeners.extend([
                ("concept:new", create_or_update_concept),
                ("concept:update", create_or_update_concept),
                ("concept:delete", delete_concept),
            ])

        for event_name, handler in listeners:
            gazu.events.add_listener(
                self.event_client,
                event_name,
                lambda data, ev=event_name, fn=handler: (
                    self._run_inbound_handler(ev, fn, data)
                ),
            )

    def get_pairing_list(self) -> dict[str, str | None]:
        """maintain the ayon project name of each kitsu project, so that we
        can check the kitsu change is in a paired project

        The endpoint lists every kitsu project, the ones that are not paired
        yet carrying a null ayon project name.
        """
        logging.info("get_pairing_list")
        res = ayon_api.get(f"{self.entrypoint}/pairing")

        assert res.status_code == 200, (
            f"{self.entrypoint}/pairing failed. "
            f" Status code '{res.status_code}': {res.detail}"
        )

        return {
            pair["kitsuProjectId"]: pair["ayonProjectName"]
            for pair in res.data
        }

    def get_paired_ayon_project(self, kitsu_project_id: str) -> str | None:
        """returns the ayon project if paired else None"""
        return self.pairing_list.get(kitsu_project_id)

    def set_paired_ayon_project(
        self, kitsu_project_id: str, ayon_project_name: str
    ):
        """pair a kitsu project with an ayon one"""
        self.pairing_list[kitsu_project_id] = ayon_project_name

    def _poll_sync_request_once(self) -> bool:
        """Poll and process at most one ``kitsu.sync_request`` job.

        Returns:
            True if a sync request was processed/attempted, False if none.
        """
        client = getattr(self, "ayon_api", ayon_api)
        job = client.enroll_event_job(
            source_topic="kitsu.sync_request",
            target_topic="kitsu.sync",
            sender=SENDER,
            description="Syncing Kitsu to Ayon",
            max_retries=3,
        )
        if not job:
            return False

        src_job = client.get_event(job["dependsOn"])
        kitsu_project_id = src_job["summary"]["kitsuProjectId"]
        ayon_project_name = src_job["project"]

        client.update_event(
            job["id"],
            sender=SENDER,
            status="in_progress",
            project_name=ayon_project_name,
            description="Syncing Kitsu project...",
        )

        try:
            project_full_sync(self, kitsu_project_id, ayon_project_name)
            self.set_paired_ayon_project(
                kitsu_project_id, ayon_project_name
            )
        except Exception as exc:
            log_traceback(
                f"Unable to sync kitsu project {ayon_project_name}"
            )
            error_text = self._redact_error_text(
                str(exc) or type(exc).__name__
            )
            tb_text = self._redact_error_text(traceback.format_exc())
            short_err = (
                error_text[:200] + "..."
                if len(error_text) > 200
                else error_text
            )
            client.update_event(
                job["id"],
                sender=SENDER,
                status="failed",
                project_name=ayon_project_name,
                description=f"Sync failed: {short_err}",
                payload={
                    "error": error_text,
                    "message": tb_text,
                },
            )
        else:
            client.update_event(
                job["id"],
                sender=SENDER,
                status="finished",
                project_name=ayon_project_name,
                description="Kitsu sync finished",
                payload={},
            )
        return True

    def _run_startup_full_sync(
        self, project_id: str, project_name: str
    ) -> bool:
        """Run startup full sync and record outcome in ``kitsu.sync`` events.

        Args:
            project_id: Kitsu project ID.
            project_name: Paired AYON project name.

        Returns:
            True on success, False on failure.
        """
        client = getattr(self, "ayon_api", ayon_api)
        event_id = None
        if hasattr(client, "dispatch_event"):
            try:
                res = client.dispatch_event(
                    "kitsu.sync",
                    sender=SENDER,
                    project_name=project_name,
                    description="Startup syncing Kitsu project...",
                    finished=False,
                    store=True,
                )
                event_id = self._extract_event_id(res)
                if event_id and hasattr(client, "update_event"):
                    client.update_event(
                        event_id,
                        sender=SENDER,
                        status="in_progress",
                        project_name=project_name,
                        description="Startup syncing Kitsu project...",
                    )
            except Exception:
                log_traceback(
                    f"Unable to record startup kitsu.sync event for "
                    f"{project_name}"
                )

        try:
            project_full_sync(self, project_id, project_name)
        except Exception as exc:
            tb_text = traceback.format_exc()
            log_traceback(f"Unable to sync kitsu project {project_name}")
            error_text = self._redact_error_text(
                str(exc) or type(exc).__name__
            )
            safe_tb = self._redact_error_text(tb_text)
            short_err = (
                error_text[:200] + "..."
                if len(error_text) > 200
                else error_text
            )
            if event_id and hasattr(client, "update_event"):
                try:
                    client.update_event(
                        event_id,
                        sender=SENDER,
                        status="failed",
                        project_name=project_name,
                        description=f"Startup sync failed: {short_err}",
                        payload={
                            "error": error_text,
                            "message": safe_tb,
                        },
                    )
                except Exception:
                    log_traceback(
                        f"Unable to update startup kitsu.sync failure for "
                        f"{project_name}"
                    )
            self._dispatch_service_error(
                f"Startup full sync failed for project {project_name}: {exc}",
                traceback_text=tb_text,
                project_name=project_name,
            )
            return False

        if event_id and hasattr(client, "update_event"):
            try:
                client.update_event(
                    event_id,
                    sender=SENDER,
                    status="finished",
                    project_name=project_name,
                    description="Kitsu startup sync finished",
                    payload={},
                )
            except Exception:
                log_traceback(
                    f"Unable to update startup kitsu.sync completion for "
                    f"{project_name}"
                )
        return True

    def start_processing(self):
        logging.info("KitsuProcessor started")
        startup = True

        while True:
            # Sync all paired projects
            if startup:
                logging.info("Running sync for all paired projects")
                for project_id, project_name in self.pairing_list.items():
                    if not project_id or not project_name:
                        continue
                    self._run_startup_full_sync(project_id, project_name)
                startup = False

            if not self._poll_sync_request_once():
                time.sleep(5)

        logging.info("KitsuProcessor finished processing")
        gazu.log_out()

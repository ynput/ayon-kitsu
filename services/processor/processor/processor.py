import os
import socket
import sys
import threading
import time
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


class KitsuServerError(Exception):
    pass


class KitsuSettingsError(Exception):
    pass


class KitsuProcessor:
    is_running: bool = True

    def __init__(self):
        #
        # Connect to Ayon
        #
        try:
            ayon_api.init_service()
            # Mark every AYON REST request made by the Processor as sync
            # originated (X-Sender / X-Sender-Type headers), so the events
            # they cause can be told apart from user edits (Req. 5.7).
            ayon_api.set_sender(SENDER)
            ayon_api.set_sender_type("kitsu_sync")
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
        self.outbound = None
        self.is_running = True
        self.in_flight_creations: dict[str, threading.Event] = {}
        self.in_flight_lock = threading.Lock()
        self._active_creation_event: threading.Event | None = None
        self.deferred_inbound_events: list = []
        self.deferred_inbound_lock = threading.Lock()

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

            try:
                self.kitsu_login_email = (
                    ayon_api.get_secret(email_secret)["value"]
                )
                self.kitsu_login_password = (
                    ayon_api.get_secret(password_secret)["value"]
                )
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

        # init event client
        self.kitsu_events_url = self.kitsu_server_url.replace(
            "api", "socket.io"
        )
        gazu.set_event_host(self.kitsu_events_url)
        self.event_client = gazu.events.init()

        # ============= Add Kitsu Event Listeners ==============
        gazu_listener_thread = threading.Thread(target=self.run_gazu_listeners)
        gazu_listener_thread.start()

        self.outbound = self._create_outbound_safe()

    def run_gazu_listeners(self):
        gazu.events.add_listener(
            self.event_client,
            "project:update",
            lambda data: update_project(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "project:delete",
            lambda data: delete_project(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "asset:new",
            lambda data: create_or_update_asset(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "asset:update",
            lambda data: create_or_update_asset(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "asset:delete",
            lambda data: delete_asset(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "episode:new",
            lambda data: create_or_update_episode(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "episode:update",
            lambda data: create_or_update_episode(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "episode:delete",
            lambda data: delete_episode(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "sequence:new",
            lambda data: create_or_update_sequence(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "sequence:update",
            lambda data: create_or_update_sequence(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "sequence:delete",
            lambda data: delete_sequence(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "shot:new",
            lambda data: create_or_update_shot(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "shot:update",
            lambda data: create_or_update_shot(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "shot:casting-update",
            lambda data: create_or_update_casting(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "asset:casting-update",
            lambda data: create_or_update_casting(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "shot:delete",
            lambda data: delete_shot(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "task:new",
            lambda data: create_or_update_task(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "task:update",
            lambda data: create_or_update_task(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "task:delete",
            lambda data: delete_task(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "edit:new",
            lambda data: create_or_update_edit(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "edit:update",
            lambda data: create_or_update_edit(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "edit:delete",
            lambda data: delete_edit(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "person:new",
            lambda data: create_or_update_person(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "person:update",
            lambda data: create_or_update_person(self, data),
        )
        gazu.events.add_listener(
            self.event_client,
            "person:delete",
            lambda data: delete_person(self, data),
        )
        # Concept events were fixed in Zou 0.19.0, so listen only if
        # the user is running Zou euqual or above 0.19.0
        if tuple(gazu.client.get_api_version().split(".")) >= ("0", "19", "0"):
            gazu.events.add_listener(
                self.event_client,
                "concept:new",
                lambda data: create_or_update_concept(self, data),
            )
            gazu.events.add_listener(
                self.event_client,
                "concept:update",
                lambda data: create_or_update_concept(self, data),
            )
            gazu.events.add_listener(
                self.event_client,
                "concept:delete",
                lambda data: delete_concept(self, data),
            )
        logging.info("Gazu event listeners added")
        gazu.events.run_client(self.event_client)

    def start_in_flight_creation(self) -> threading.Event:
        """Register outbound in-flight creation before sending request."""
        with self.in_flight_lock:
            ev = getattr(self, "_active_creation_event", None)
            if ev is None:
                ev = threading.Event()
                self._active_creation_event = ev
            return ev

    def register_in_flight_creation(
        self, kitsu_id: str | None = None
    ) -> threading.Event:
        """Register outbound in-flight creation to coordinate with inbound."""
        with self.in_flight_lock:
            ev = getattr(self, "_active_creation_event", None)
            if ev is None:
                ev = threading.Event()
                self._active_creation_event = ev
            if kitsu_id:
                self.in_flight_creations[kitsu_id] = ev
            return ev

    def finish_in_flight_creation(
        self, kitsu_id: str | None = None
    ) -> None:
        """Signal that creation request and writeback finished."""
        with self.in_flight_lock:
            if kitsu_id:
                ev = self.in_flight_creations.pop(kitsu_id, None)
                if ev is not None:
                    ev.set()
            active_ev = getattr(self, "_active_creation_event", None)
            if active_ev is not None:
                active_ev.set()
                self._active_creation_event = None
        self.process_deferred_inbound_events()

    def defer_inbound_call(
        self, func: Any, *args: Any, **kwargs: Any
    ) -> None:
        """Queue an inbound event callback when creation wait times out."""
        lock = getattr(self, "deferred_inbound_lock", None)
        if lock is None:
            return
        with lock:
            if not hasattr(self, "deferred_inbound_events"):
                self.deferred_inbound_events = []
            self.deferred_inbound_events.append((func, args, kwargs))

    def process_deferred_inbound_events(self) -> int:
        """Replay any deferred inbound event callbacks.

        Returns:
            Number of processed deferred events.
        """
        lock = getattr(self, "deferred_inbound_lock", None)
        if lock is None:
            return 0
        with lock:
            if not getattr(self, "deferred_inbound_events", None):
                return 0
            events_to_process = list(self.deferred_inbound_events)
            self.deferred_inbound_events.clear()

        processed_count = 0
        for func, args, kwargs in events_to_process:
            try:
                func(*args, **kwargs)
                processed_count += 1
            except Exception:
                log_traceback("Error executing deferred inbound event")
        return processed_count

    def wait_for_in_flight_creation(
        self, kitsu_id: str, timeout: float = 5.0
    ) -> bool:
        """Wait if an inbound event matches an in-flight outbound creation."""
        with self.in_flight_lock:
            ev = self.in_flight_creations.get(kitsu_id)
            if ev is None:
                ev = getattr(self, "_active_creation_event", None)
        if ev is not None:
            return ev.wait(timeout=timeout)
        return True

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
        if getattr(self, "outbound", None):
            try:
                self.outbound.settings_watcher.refresh()
            except Exception:
                log_traceback(
                    "Error refreshing settings after pairing update"
                )

    def get_outbound_pairings(self) -> dict[str, str]:
        """Return mapping of ayon_project_name -> kitsu_project_id."""
        if not isinstance(self.pairing_list, dict):
            return {}
        return {
            ayon_name: kitsu_id
            for kitsu_id, ayon_name in self.pairing_list.items()
            if kitsu_id and ayon_name
        }

    def pull_kitsu_task(
        self, kitsu_id: str, kitsu_task: dict | None = None
    ) -> None:
        """Pull task from Kitsu into AYON on conflict (Req 9.4)."""
        proj_id = ""
        if isinstance(kitsu_task, dict):
            proj_id = kitsu_task.get("project_id", "")
        res = create_or_update_task(
            self,
            {"task_id": kitsu_id, "project_id": proj_id},
        )
        if res is not None:
            st = getattr(res, "status_code", getattr(res, "status", 200))
            if st and st >= 400:
                raise RuntimeError(
                    f"Inbound pull failed with HTTP status {st}"
                )

    def pull_kitsu_entity(
        self,
        kitsu_id: str,
        entity_type: str = "",
        kitsu_entity: dict | None = None,
    ) -> None:
        """Pull entity from Kitsu into AYON on conflict (Req 9.4)."""
        proj_id = ""
        if isinstance(kitsu_entity, dict):
            proj_id = kitsu_entity.get("project_id", "")
        ent_type = entity_type.lower()
        if ent_type == "task":
            return self.pull_kitsu_task(kitsu_id, kitsu_entity)

        from .update_from_kitsu import (
            create_or_update_asset,
            create_or_update_concept,
            create_or_update_edit,
            create_or_update_episode,
            create_or_update_sequence,
            create_or_update_shot,
        )

        res = None
        if ent_type == "shot":
            res = create_or_update_shot(
                self, {"shot_id": kitsu_id, "project_id": proj_id}
            )
        elif ent_type == "asset":
            res = create_or_update_asset(
                self, {"asset_id": kitsu_id, "project_id": proj_id}
            )
        elif ent_type == "sequence":
            res = create_or_update_sequence(
                self, {"sequence_id": kitsu_id, "project_id": proj_id}
            )
        elif ent_type == "episode":
            res = create_or_update_episode(
                self, {"episode_id": kitsu_id, "project_id": proj_id}
            )
        elif ent_type == "edit":
            res = create_or_update_edit(
                self, {"edit_id": kitsu_id, "project_id": proj_id}
            )
        elif ent_type == "concept":
            res = create_or_update_concept(
                self, {"concept_id": kitsu_id, "project_id": proj_id}
            )
        else:
            raise ValueError(
                f"Unsupported entity type for inbound pull: {ent_type}"
            )

        if res is not None:
            st = getattr(res, "status_code", getattr(res, "status", 200))
            if st and st >= 400:
                raise RuntimeError(
                    f"Inbound pull failed with HTTP status {st}"
                )

    def _poll_sync_request_once(self) -> bool:
        """Poll and process at most one kitsu.sync_request job.

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
        except Exception:
            log_traceback(
                f"Unable to sync kitsu project {ayon_project_name}"
            )
            client.update_event(
                job["id"],
                sender=SENDER,
                status="failed",
                project_name=ayon_project_name,
                description="Sync failed",
            )
        else:
            client.update_event(
                job["id"],
                sender=SENDER,
                status="finished",
                project_name=ayon_project_name,
                description="Kitsu sync finished",
            )
        return True

    def poll_sync_request(self) -> bool:
        """Poll sync request (called by OutboundJobRunner, Req 4.6)."""
        return self._poll_sync_request_once()

    def _create_outbound_safe(self):
        """Create OutboundJobRunner safely without failing Inbound_Sync."""
        try:
            from .outbound.identity import IdentityResolver
            from .outbound.kitsu_writer import KitsuWriter
            from .outbound.runner import OutboundJobRunner
            from .outbound.settings_watch import (
                GateHistory,
                SettingsWatcher,
            )

            client = getattr(self, "ayon_api", ayon_api)
            gate_history = getattr(self, "_outbound_gate_history", None)
            if gate_history is None:
                gate_history = GateHistory(client)
                gate_history.loaded = False
                self._outbound_gate_history = gate_history

            watcher = getattr(self, "_outbound_settings_watcher", None)
            if watcher is None:
                watcher = SettingsWatcher(
                    client,
                    pairing_list_getter=self.get_outbound_pairings,
                    gate_history=gate_history,
                    addon_name=getattr(self, "addon_name", None),
                    addon_version=getattr(self, "addon_version", None),
                )
                self._outbound_settings_watcher = watcher

            writer = KitsuWriter(
                self.kitsu_server_url,
                login=self.kitsu_login_email,
                password=self.kitsu_login_password,
            )
            identity = IdentityResolver(
                client,
                writer,
                entrypoint=getattr(self, "entrypoint", "/addons/kitsu/0.0.0"),
            )
            self._outbound_init_failed = False
            return OutboundJobRunner(
                processor=self,
                ayon_client=client,
                writer=writer,
                settings_watcher=watcher,
                gate_history=gate_history,
                identity_resolver=identity,
                sender=SENDER,
            )
        except Exception:
            self._outbound_init_failed = True
            log_traceback(
                "Outbound Sync unavailable; inbound remains active"
            )
            return None

    def start_processing(self):
        logging.info("KitsuProcessor started")

        # Outbound startup sequence
        started_at = time.time()
        drain_failed = False
        if getattr(self, "outbound", None) is None:
            self.outbound = self._create_outbound_safe()
            if getattr(self, "outbound", None) is None:
                drain_failed = True
                watcher = getattr(self, "_outbound_settings_watcher", None)
                if watcher is not None:
                    try:
                        watcher.refresh()
                    except Exception:
                        log_traceback(
                            "Error in fallback outbound settings refresh"
                        )

        if getattr(self, "outbound", None):
            try:
                self.outbound.gate_history.load(started_at=started_at)
            except Exception:
                self.outbound.gate_history.loaded = False
                drain_failed = True
                log_traceback("Error in outbound startup gate history load")

            try:
                self.outbound.settings_watcher.refresh()
                has_invalid = any(
                    not self.outbound.settings_watcher.has_effective_toggles(p)
                    for p in self.get_outbound_pairings()
                )
                if has_invalid:
                    drain_failed = True
                    logging.error(
                        "Startup settings invalid or unreadable for one or "
                        "more outbound pairings; failing closed (Req 10.5)"
                    )
            except Exception:
                drain_failed = True
                log_traceback("Error in outbound startup settings refresh")

            if not drain_failed:
                try:
                    has_enabled = any(
                        self.outbound.settings_watcher.get_effective_toggles(
                            p
                        ).get("master")
                        for p in self.get_outbound_pairings()
                    )
                    if has_enabled:
                        failed_jobs = self.outbound.drain()
                        if failed_jobs:
                            summary_str = ", ".join(
                                f"job_id={j.get('job_id')} "
                                f"entity_id={j.get('entity_id')} "
                                f"category={j.get('category')}"
                                for j in failed_jobs
                            )
                            logging.warning(
                                "Startup drain: outbound jobs failed on final "
                                f"attempt before full sync: {summary_str}"
                            )
                except Exception:
                    drain_failed = True
                    log_traceback("Error in outbound startup drain")

        # Sync all paired projects
        logging.info("Running sync for all paired projects")
        for project_id, project_name in self.pairing_list.items():
            if not project_id or not project_name:
                continue
            watcher = (
                self.outbound.settings_watcher
                if getattr(self, "outbound", None)
                else getattr(self, "_outbound_settings_watcher", None)
            )
            if getattr(self, "outbound", None) or drain_failed:
                has_known = bool(
                    watcher is not None
                    and (
                        watcher.has_effective_toggles(project_name)
                        if hasattr(watcher, "has_effective_toggles")
                        else project_name
                        in getattr(watcher, "effective_by_project", {})
                    )
                )
                if not has_known:
                    # Toggle state unknown or invalid due to startup failure;
                    # fail closed to prevent overwriting undrained edits.
                    logging.error(
                        "Skipping full sync for %s: effective settings "
                        "invalid or unreadable (Requirement 10.5)",
                        project_name,
                    )
                    continue
                elif drain_failed:
                    is_enabled = bool(
                        watcher.get_effective_toggles(project_name).get(
                            "master"
                        )
                    )
                    if is_enabled:
                        logging.error(
                            "Skipping full sync for %s: outbound drain "
                            "failed (Requirement 10.5)",
                            project_name,
                        )
                        continue
            try:
                project_full_sync(self, project_id, project_name)
            except Exception:
                log_traceback(
                    f"Unable to sync kitsu project {project_name}"
                )

        last_refresh = time.time()
        last_reap = time.time()
        while getattr(self, "is_running", True):
            now = time.time()
            if getattr(self, "outbound", None) is None and (
                now - last_refresh >= 30
            ):
                last_refresh = now
                self.outbound = self._create_outbound_safe()
                if getattr(self, "outbound", None):
                    try:
                        self.outbound.gate_history.load(
                            started_at=started_at
                        )
                    except Exception:
                        self.outbound.gate_history.loaded = False
                        log_traceback("Error loading recovered gate history")
                    try:
                        self.outbound.settings_watcher.refresh()
                    except Exception:
                        log_traceback("Error refreshing recovered settings")

            if getattr(self, "outbound", None):
                try:
                    if now - last_refresh >= 30:
                        if not getattr(
                            self.outbound.gate_history, "loaded", True
                        ):
                            self.outbound.gate_history.load(
                                started_at=started_at
                            )
                        self.outbound.settings_watcher.refresh()
                        last_refresh = now
                except Exception:
                    log_traceback("Error refreshing settings")

                try:
                    if now - last_reap >= 60:
                        self.outbound.reap_stale()
                        last_reap = now
                except Exception:
                    log_traceback("Error reaping stale jobs")

                try:
                    if self.outbound.pending_ayon_update:
                        self.outbound.retry_pending_ayon_update()
                except Exception:
                    log_traceback("Error retrying pending AYON update")

            # Inbound deferred events check
            try:
                self.process_deferred_inbound_events()
            except Exception:
                log_traceback("Error processing deferred inbound events")

            # 1. Inbound sync request check
            inbound_ran = False
            sync_poll_error = False
            try:
                inbound_ran = self._poll_sync_request_once()
            except Exception:
                log_traceback("Error polling sync request")
                sync_poll_error = True

            if inbound_ran:
                continue

            # 2. Outbound poll_once check if any paired project enabled
            outbound_did_work = False
            if not sync_poll_error and getattr(self, "outbound", None):
                try:
                    gh = getattr(self.outbound, "gate_history", None)
                    if gh is not None and not getattr(gh, "loaded", True):
                        gh.load(started_at=started_at)
                        self.outbound.settings_watcher.refresh()
                    has_enabled = any(
                        self.outbound.settings_watcher.get_effective_toggles(
                            p
                        ).get("master")
                        for p in self.get_outbound_pairings()
                    )
                    if has_enabled:
                        outbound_did_work = self.outbound.poll_once()
                except Exception:
                    log_traceback("Error in outbound poll_once")

            if outbound_did_work:
                continue

            time.sleep(2)

        logging.info("KitsuProcessor finished processing")
        gazu.log_out()

    def stop(self) -> None:
        """Signal the processing loop to terminate gracefully."""
        self.is_running = False

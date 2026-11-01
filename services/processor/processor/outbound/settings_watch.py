"""Settings watcher and gate history tracking (Task 9.1).

Validates: Requirements 2.6, 2.7, 2.10, 4.7, 4.12, 4.13.
"""

import logging
import time
from typing import Any, Dict, Iterable, List, Optional

from .constants import (
    GATE_TOPIC,
    SETTINGS_REFRESH_S,
    SYNC_CATEGORIES,
)
from .gating import (
    ensure_dict,
    find_unknown_gap,
    resolve_effective_toggles,
    to_seconds_safe,
    toggles_at,
)

logger = logging.getLogger(__name__)


class GateHistory:
    """Manages gate snapshots, heartbeats, gaps and skip counts."""

    def __init__(self, ayon_client: Any, clock: Optional[Any] = None):
        """Initialize GateHistory.

        Args:
            ayon_client: AYON API client.
            clock: Injected clock callable (returns float epoch seconds).
        """
        self.ayon_client = ayon_client
        self.clock = clock or time.time
        self.history: Dict[str, List[Dict[str, Any]]] = {}
        self.gaps: List[Dict[str, Any]] = []
        self.last_observed_at: Optional[float] = None
        self.latest_gate_event_id: Optional[str] = None
        self.current_gap_event_id: Optional[str] = None
        self.skipped_events_count: int = 0
        self.unpersisted_snapshots: Dict[str, Dict[str, Any]] = {}
        self.loaded: bool = True

    def load(
        self,
        started_at: Optional[float] = None,
        settings_addon_name: str = "kitsu",
    ) -> Optional[Dict[str, Any]]:
        """Load gate history at startup and detect Unknown_Toggle_Gap.

        Args:
            started_at: Processor start time in epoch seconds.
            settings_addon_name: Addon name to filter settings.changed events.

        Returns:
            The detected gap dict if an unknown gap exists, else None.
        """
        now = float(started_at if started_at is not None else self.clock())
        latest_obs: Optional[float] = None

        # 1. Load existing kitsu.outbound_gate events
        gate_events = []
        if hasattr(self.ayon_client, "get_events"):
            try:
                gate_events = list(
                    self.ayon_client.get_events(
                        topics=[GATE_TOPIC],
                        fields=[
                            "id",
                            "topic",
                            "summary",
                            "createdAt",
                            "project",
                        ],
                    )
                )
            except Exception as exc:
                self.loaded = False
                logger.error("Could not load gate events: %s", exc)
                raise RuntimeError(
                    f"Could not load gate events: {exc}"
                ) from exc

        for event in gate_events:
            summary = ensure_dict(event.get("summary"))
            event_id = event.get("id")
            # Snapshot event
            if "toggles" in summary and "project" in summary:
                proj = summary["project"]
                obs_at = summary.get("lastObservedAt") or summary.get(
                    "observedAt"
                )
                if obs_at is not None:
                    obs_f = to_seconds_safe(obs_at)
                    if obs_f is not None:
                        if latest_obs is None or obs_f > latest_obs:
                            latest_obs = obs_f
                            self.latest_gate_event_id = event_id

                snap = {
                    "project": proj,
                    "toggles": summary.get("toggles"),
                    "observedAt": summary.get("observedAt"),
                }
                if snap not in self.history.setdefault(proj, []):
                    self.history[proj].append(snap)
            # Gap marker event
            elif "gap" in summary:
                if summary not in self.gaps:
                    self.gaps.append(summary)

        for snaps in self.history.values():
            snaps.sort(
                key=lambda s: to_seconds_safe(s.get("observedAt")) or 0.0
            )

        if latest_obs is not None and (
            self.last_observed_at is None or latest_obs > self.last_observed_at
        ):
            self.last_observed_at = latest_obs
        self.loaded = True

        # 2. Check for settings.changed events
        settings_changed_times: List[float] = []
        query_failed = False
        if hasattr(self.ayon_client, "get_events"):
            try:
                ch_events = list(
                    self.ayon_client.get_events(
                        topics=["settings.changed"],
                        fields=["id", "topic", "summary", "createdAt"],
                    )
                )
                for ch in ch_events:
                    ch_summary = ensure_dict(ch.get("summary"))
                    addon = (
                        ch_summary.get("addon_name") or ch.get("addon_name")
                    )
                    if addon == settings_addon_name or not addon:
                        c_time = ch.get("createdAt") or ch.get("created_at")
                        if c_time is not None:
                            settings_changed_times.append(c_time)
            except Exception as exc:
                logger.warning("Could not query settings.changed: %s", exc)
                query_failed = True

        # 3. Detect gap
        gap: Optional[Dict[str, Any]] = None
        if latest_obs is not None:
            gap = find_unknown_gap(
                latest_obs, now, settings_changed_times
            )
            # If query failed, fail closed by treating gap as unknown
            # (Requirements 2.8, 4.12)
            if query_failed and gap is not None:
                gap["unknown"] = True

        if gap is not None:
            gap_summary = {"gap": gap, "skippedEvents": 0}
            self.gaps.append(gap_summary)
            if hasattr(self.ayon_client, "dispatch_event"):
                try:
                    res = self.ayon_client.dispatch_event(
                        GATE_TOPIC,
                        summary=gap_summary,
                        finished=True,
                    )
                    event_id = None
                    if hasattr(res, "data") and isinstance(res.data, dict):
                        event_id = res.data.get("id")
                    elif isinstance(res, dict):
                        event_id = res.get("id")
                    if event_id:
                        self.current_gap_event_id = str(event_id)
                except Exception as exc:
                    logger.warning("Could not persist gap marker: %s", exc)

        return gap

    @staticmethod
    def _extract_event_id(res: Any) -> Optional[str]:
        if hasattr(res, "data") and isinstance(res.data, dict):
            eid = res.data.get("id")
            return str(eid) if eid else None
        if isinstance(res, dict):
            eid = res.get("id")
            return str(eid) if eid else None
        return None

    def record_observation(
        self,
        project_name: str,
        toggles: Dict[str, Any],
        now: Optional[float] = None,
    ) -> Optional[str]:
        """Record effective toggles if they changed and persist event."""
        moment = float(now if now is not None else self.clock())
        proj_hist = self.history.setdefault(project_name, [])

        # Check if changed from chronologically latest snapshot or unpersisted
        changed = True
        has_unpersisted = project_name in self.unpersisted_snapshots
        last_snapshot = None
        if proj_hist:
            last_snapshot = max(
                proj_hist,
                key=lambda s: to_seconds_safe(s.get("observedAt")) or 0.0,
            )
        if last_snapshot is not None and not has_unpersisted:
            if last_snapshot.get("toggles") == toggles:
                changed = False

        if changed:
            if (
                last_snapshot is None
                or last_snapshot.get("toggles") != toggles
            ):
                snapshot = {
                    "project": project_name,
                    "toggles": toggles,
                    "observedAt": moment,
                }
                proj_hist.append(snapshot)
                proj_hist.sort(
                    key=lambda s: to_seconds_safe(s.get("observedAt")) or 0.0
                )
            else:
                snapshot = last_snapshot

            if not hasattr(self.ayon_client, "dispatch_event"):
                self.last_observed_at = moment
                return None

            for other_proj, other_snap in list(
                self.unpersisted_snapshots.items()
            ):
                if other_proj == project_name:
                    continue
                try:
                    res = self.ayon_client.dispatch_event(
                        GATE_TOPIC,
                        project_name=other_proj,
                        summary={
                            "project": other_proj,
                            "toggles": other_snap.get("toggles"),
                            "observedAt": other_snap.get("observedAt", moment),
                            "lastObservedAt": moment,
                        },
                        finished=True,
                    )
                    eid = self._extract_event_id(res)
                    if eid:
                        self.latest_gate_event_id = eid
                    self.unpersisted_snapshots.pop(other_proj, None)
                except Exception as exc:
                    self.unpersisted_snapshots[project_name] = snapshot
                    logger.warning("Could not persist gate snapshot: %s", exc)
                    return None

            summary = {
                "project": project_name,
                "toggles": toggles,
                "observedAt": snapshot.get("observedAt", moment),
                "lastObservedAt": moment,
            }
            try:
                res = self.ayon_client.dispatch_event(
                    GATE_TOPIC,
                    project_name=project_name,
                    summary=summary,
                    finished=True,
                )
                event_id = self._extract_event_id(res)
                if event_id:
                    self.latest_gate_event_id = event_id
                self.unpersisted_snapshots.pop(project_name, None)
                self.last_observed_at = moment
                return event_id
            except Exception as exc:
                self.unpersisted_snapshots[project_name] = snapshot
                logger.warning("Could not persist gate snapshot: %s", exc)

        return None

    def heartbeat(self, now: Optional[float] = None) -> None:
        """Update lastObservedAt on the latest gate event."""
        moment = float(now if now is not None else self.clock())

        # Retry unpersisted snapshots before advancing the durable heartbeat
        if self.unpersisted_snapshots:
            if hasattr(self.ayon_client, "dispatch_event"):
                for proj, snap in list(self.unpersisted_snapshots.items()):
                    try:
                        res = self.ayon_client.dispatch_event(
                            GATE_TOPIC,
                            project_name=proj,
                            summary={
                                "project": proj,
                                "toggles": snap.get("toggles"),
                                "observedAt": snap.get("observedAt", moment),
                                "lastObservedAt": moment,
                            },
                            finished=True,
                        )
                        eid = self._extract_event_id(res)
                        if eid:
                            self.latest_gate_event_id = eid
                        self.unpersisted_snapshots.pop(proj, None)
                    except Exception as exc:
                        logger.warning(
                            "Could not persist retry gate snapshot: %s", exc
                        )
            if self.unpersisted_snapshots:
                return

        if self.latest_gate_event_id and hasattr(
            self.ayon_client, "update_event"
        ):
            try:
                self.ayon_client.update_event(
                    self.latest_gate_event_id,
                    summary={"lastObservedAt": moment},
                )
                self.last_observed_at = moment
            except Exception as exc:
                logger.warning("Could not update gate heartbeat: %s", exc)
        else:
            self.last_observed_at = moment

    def record_gap_skip(self) -> None:
        """Increment count of events skipped under Requirement 4.12."""
        self.skipped_events_count += 1
        if self.current_gap_event_id and hasattr(
            self.ayon_client, "update_event"
        ):
            try:
                self.ayon_client.update_event(
                    self.current_gap_event_id,
                    summary={"skippedEvents": self.skipped_events_count},
                )
            except Exception as exc:
                logger.warning("Could not update gap skip count: %s", exc)

    def toggles_at(
        self, project_name: str, created_at: Any
    ) -> Dict[str, Any]:
        """Classify toggle state at event creation time."""
        proj_hist = self.history.get(project_name, [])
        return toggles_at(proj_hist, self.gaps, created_at)


class SettingsWatcher:
    """Watches addon settings and computes effective project toggles."""

    def __init__(
        self,
        ayon_client: Any,
        pairing_list_getter: Optional[Any] = None,
        gate_history: Optional[GateHistory] = None,
        clock: Optional[Any] = None,
        refresh_interval_s: float = SETTINGS_REFRESH_S,
        addon_name: Optional[str] = None,
        addon_version: Optional[str] = None,
    ):
        """Initialize SettingsWatcher.

        Args:
            ayon_client: AYON API client.
            pairing_list_getter: Callable returning paired project names/dict.
            gate_history: GateHistory instance to update on changes.
            clock: Injected clock callable.
            refresh_interval_s: Refresh period in seconds (default: 30s).
            addon_name: Addon name (e.g. 'kitsu').
            addon_version: Addon version string.
        """
        self.ayon_client = ayon_client
        self.pairing_list_getter = pairing_list_getter
        self.gate_history = gate_history
        self.clock = clock or time.time
        self.refresh_interval_s = float(refresh_interval_s)
        self.last_refresh_time: float = 0.0
        self.effective_by_project: Dict[str, Dict[str, Any]] = {}
        self.addon_name = addon_name
        self.addon_version = addon_version
        if self.addon_name is None and hasattr(
            self.ayon_client, "get_service_addon_name"
        ):
            try:
                self.addon_name = self.ayon_client.get_service_addon_name()
            except Exception:
                pass
        if self.addon_version is None and hasattr(
            self.ayon_client, "get_service_addon_version"
        ):
            try:
                self.addon_version = (
                    self.ayon_client.get_service_addon_version()
                )
            except Exception:
                pass

    def get_paired_projects(self) -> Iterable[str]:
        """Return list of paired AYON project names."""
        if not self.pairing_list_getter:
            return ()
        try:
            pairing = self.pairing_list_getter()
            if isinstance(pairing, dict):
                return list(pairing.keys())
            if isinstance(pairing, (list, tuple, set)):
                return list(pairing)
        except Exception as exc:
            logger.warning("Could not read pairing list: %s", exc)
        return ()

    def _read_project_settings(
        self, project_name: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch project-specific settings via project-aware addon API."""
        addon_name = self.addon_name or "kitsu"
        addon_version = self.addon_version

        # 1. Project-aware API on ServerAPI / ayon_api
        if (
            hasattr(self.ayon_client, "get_addon_project_settings")
            and addon_version
        ):
            return self.ayon_client.get_addon_project_settings(
                addon_name, addon_version, project_name
            )

        if hasattr(self.ayon_client, "get_addon_settings") and addon_version:
            return self.ayon_client.get_addon_settings(
                addon_name, addon_version, project_name=project_name
            )

        # 2. Module-level or fake fallback if it accepts project_name
        if hasattr(self.ayon_client, "get_service_addon_settings"):
            try:
                return self.ayon_client.get_service_addon_settings(
                    project_name=project_name
                )
            except TypeError:
                pass

        return None

    def refresh(self) -> Dict[str, Dict[str, Any]]:
        """Refresh studio and project settings (Requirement 2.6, 2.7, 2.10).

        Returns:
            Dict mapping project_name to effective toggles.
        """
        now = float(self.clock())

        # 1. Read studio settings
        studio_settings: Optional[Dict[str, Any]] = None
        try:
            if hasattr(self.ayon_client, "get_service_addon_settings"):
                studio_settings = (
                    self.ayon_client.get_service_addon_settings()
                )
        except Exception as exc:
            logger.error("Could not read studio addon settings: %s", exc)

        # 2. For each paired project, read overrides and compute effective
        paired_projects = list(self.get_paired_projects())
        for project_name in paired_projects:
            project_settings: Optional[Dict[str, Any]] = None
            read_failed = False
            read_error = ""
            try:
                project_settings = self._read_project_settings(project_name)
            except Exception as exc:
                read_failed = True
                read_error = str(exc)
                logger.warning(
                    "Could not read settings for project %s: %s",
                    project_name,
                    exc,
                )

            if read_failed:
                effective = {
                    "valid": False,
                    "error": (
                        f"project_settings for '{project_name}' could not "
                        f"be read: {read_error}"
                    ),
                    "master": False,
                    "categories": {cat: False for cat in SYNC_CATEGORIES},
                    "conflict_policy": "kitsu_wins",
                }
            else:
                effective = resolve_effective_toggles(
                    studio_settings, project_settings
                )

            if not effective.get("valid"):
                logger.error(
                    "Invalid Two_Way_Sync_Settings for project %s: %s",
                    project_name,
                    effective.get("error"),
                )

            self.effective_by_project[project_name] = effective

            if self.gate_history and getattr(
                self.gate_history, "loaded", True
            ):
                self.gate_history.record_observation(
                    project_name, effective, now
                )

        if self.gate_history and getattr(self.gate_history, "loaded", True):
            self.gate_history.heartbeat(now)

        self.last_refresh_time = now
        return self.effective_by_project

    def has_effective_toggles(self, project_name: str) -> bool:
        """Return True if valid effective toggles are cached for project."""
        cached = self.effective_by_project.get(project_name)
        return bool(cached and cached.get("valid"))

    def get_effective_toggles(self, project_name: str) -> Dict[str, Any]:
        """Get the cached effective toggles for a project."""
        if project_name in self.effective_by_project:
            return self.effective_by_project[project_name]
        return resolve_effective_toggles(None, None)

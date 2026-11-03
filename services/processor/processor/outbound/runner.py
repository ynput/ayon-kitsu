"""Outbound sync job runner lifecycle and dispatch (Tasks 10.1 & 10.3).

Validates: Requirements 2.3, 2.4, 2.11, 3.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6,
4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 4.13, 4.14, 5.1, 5.8, 10.1, 10.2, 10.4,
10.5, 10.6, 10.7, 10.8, 10.9, 13.1, 13.4, 13.5, 13.6.
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .constants import (
    AYON_RETRY_S,
    DECISION_FAILED,
    DECISION_SKIPPED,
    ENROLLED_TOPICS,
    ERROR_UNREACHABLE,
    FINAL_RETRIES_VALUE,
    MAX_ATTEMPTS,
    MAX_RETRIES,
    NONE_VALUE,
    ORIGIN_MARKERS,
    ORIGIN_SYNC_ORIGINATED,
    ORIGIN_UNKNOWN,
    RETRY_DEADLINE_S,
    RETRY_DELAY_S,
    STALE_AFTER_S,
    TARGET_TOPIC,
)
from .describe import (
    build_log_line,
    describe_job,
    redact,
)
from .gating import (
    STATE_UNKNOWN_GAP,
    categories_for,
    ensure_dict,
    gate_decision,
    to_seconds_safe,
)
from .handlers.attributes import handle_attributes
from .handlers.creation import handle_creation
from .handlers.deletion import handle_deletion
from .handlers.rename import handle_rename
from .handlers.task_assignees import handle_task_assignees
from .handlers.task_status import handle_task_status
from .identity import IdentityResolver
from .kitsu_writer import KitsuWriter
from .loop_guard import loop_guard_apply
from .models import (
    JobContext,
    JobResult,
    failed_result,
    normalize_not_written,
)
from .origin import build_enroll_filter, classify_origin
from .retry import retry_due, supersede_fields
from .settings_watch import GateHistory, SettingsWatcher

logger = logging.getLogger(__name__)

HANDLERS: Dict[str, Callable[[JobContext], JobResult]] = {
    "task_status": handle_task_status,
    "task_assignees": handle_task_assignees,
    "entity_attributes": handle_attributes,
    "entity_creation": handle_creation,
    "entity_rename": handle_rename,
    "entity_deletion": handle_deletion,
}


def _retried_fields_for_job(
    category: str, source_event: Optional[Dict[str, Any]]
) -> List[str]:
    """Derive fields targeted by a retried job for supersession check.

    Args:
        category: Outbound sync category.
        source_event: Optional source event dict.

    Returns:
        List of target field names for the category.
    """
    if category == "task_status":
        return ["task_status_id"]
    if category == "task_assignees":
        return ["assignees"]
    if category == "entity_rename":
        return ["name"]
    if category == "entity_deletion":
        return ["deleted", "deletion"]
    if category == "entity_creation":
        return ["kitsuId", "creation"]
    if category == "entity_attributes":
        if not isinstance(source_event, dict):
            return [
                "data.fps",
                "data.frame_in",
                "data.frame_out",
                "nb_frames",
                "data.resolution",
                "description",
            ]
        payload = source_event.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        changed = payload.get("newValue")
        if changed is None:
            changed = payload.get("changed") or {}
        if not isinstance(changed, dict):
            changed = {}
        fields: List[str] = []
        if "fps" in changed:
            fields.append("data.fps")
        if "frameStart" in changed:
            fields.extend(["data.frame_in", "nb_frames"])
        if "frameEnd" in changed:
            fields.extend(["data.frame_out", "nb_frames"])
        if "resolutionWidth" in changed or "resolutionHeight" in changed:
            fields.append("data.resolution")
        if "description" in changed:
            fields.append("description")
        for k in changed:
            if (
                k
                in (
                    "data.fps",
                    "data.frame_in",
                    "data.frame_out",
                    "nb_frames",
                    "data.resolution",
                    "description",
                )
                and k not in fields
            ):
                fields.append(k)
        if not fields:
            return [
                "data.fps",
                "data.frame_in",
                "data.frame_out",
                "nb_frames",
                "data.resolution",
                "description",
            ]
        return sorted(set(fields))
    return ["task_status_id"]


class OutboundJobRunner:
    """Enrolls and processes Outbound_Jobs sequentially."""

    TARGET_TOPIC = TARGET_TOPIC
    MAX_RETRIES = MAX_RETRIES
    STALE_AFTER_S = STALE_AFTER_S
    RETRY_DELAY_S = RETRY_DELAY_S
    RETRY_DEADLINE_S = RETRY_DEADLINE_S
    AYON_RETRY_S = AYON_RETRY_S

    def __init__(
        self,
        processor: Any = None,
        clock: Optional[Callable[[], float]] = None,
        ayon_client: Optional[Any] = None,
        writer: Optional[Any] = None,
        settings_watcher: Optional[SettingsWatcher] = None,
        gate_history: Optional[GateHistory] = None,
        identity_resolver: Optional[IdentityResolver] = None,
        sender: Optional[str] = None,
    ):
        self.processor = processor
        self.clock = clock or time.time
        self.ayon_client = ayon_client or getattr(processor, "ayon_api", None)
        self.writer = writer
        self.settings_watcher = settings_watcher
        self.gate_history = gate_history
        self.identity_resolver = identity_resolver
        self.sender = (
            sender
            or getattr(processor, "sender", None)
            or "kitsu-processor-host"
        )
        self.enrolled_topics = list(ENROLLED_TOPICS)
        self.enroll_filter_supported = True
        self.loop_guard_state: Dict[tuple, Dict[str, Any]] = {}
        self.held_job: Optional[Dict[str, Any]] = None
        self.pending_ayon_update: Optional[Dict[str, Any]] = None
        self.total_sync_request_s: float = 0.0
        self.last_sync_request_poll: float = 0.0
        self.failed_final_jobs: List[Dict[str, Any]] = []
        self.last_enroll_error: Optional[Exception] = None
        self.in_drain: bool = False

        # Lazy initialize dependencies if not passed
        if self.gate_history is None and self.ayon_client is not None:
            self.gate_history = GateHistory(self.ayon_client, clock=self.clock)
        if self.settings_watcher is None and self.ayon_client is not None:
            self.settings_watcher = SettingsWatcher(
                self.ayon_client,
                pairing_list_getter=self.get_paired_projects,
                gate_history=self.gate_history,
                clock=self.clock,
            )
        if self.writer is None and processor is not None:
            host = getattr(processor, "kitsu_host", None)
            if host:
                try:
                    self.writer = KitsuWriter(host, clock=self.clock)
                except Exception as exc:
                    logger.warning(
                        "Could not initialize KitsuWriter: %s",
                        redact(str(exc), self._get_secrets()),
                    )
        if (
            self.identity_resolver is None
            and self.ayon_client is not None
            and self.writer is not None
        ):
            self.identity_resolver = IdentityResolver(
                self.ayon_client, self.writer
            )

    def _get_secrets(self) -> List[str]:
        """Collect credentials and tokens for redaction (13.6)."""
        secrets: List[str] = []
        if self.processor is not None:
            for attr in (
                "kitsu_login_password",
                "kitsu_login_email",
                "kitsu_pwd",
                "kitsu_password",
                "kitsu_login",
                "session_token",
            ):
                val = getattr(self.processor, attr, None)
                if val:
                    secrets.append(str(val))
        if self.writer is not None:
            for attr in ("password", "session_token", "login"):
                val = getattr(self.writer, attr, None)
                if val:
                    secrets.append(str(val))
            for val in getattr(self.writer, "secrets", []):
                if val:
                    secrets.append(str(val))
            for val in getattr(self.writer, "secret_values", []):
                if val:
                    secrets.append(str(val))
        if self.ayon_client is not None:
            for attr in ("api_key", "token"):
                val = getattr(self.ayon_client, attr, None)
                if val:
                    secrets.append(str(val))
        return [s for s in secrets if s]

    def get_paired_projects(self) -> List[str]:
        """Return paired AYON project names from the processor contract."""
        if self.processor is None:
            return []
        return list(self.processor.get_outbound_pairings())

    def get_kitsu_project_id(self, project_name: str) -> str:
        """Return the Kitsu project paired with an AYON project."""
        if self.processor is None:
            return ""
        return self.processor.get_outbound_pairings().get(project_name, "")

    def loop_guard_check(self, entity_id: str, field: str) -> Dict[str, Any]:
        """Run loop guard check for an entity field using current time."""
        now = float(self.clock())
        base_state = (
            self._pending_guard_state
            if getattr(self, "_pending_guard_state", None) is not None
            else self.loop_guard_state
        )
        res, new_state = loop_guard_apply(base_state, entity_id, field, now)
        self._pending_guard_state = new_state
        return res

    def loop_guard_commit(self, fields: Optional[List[str]] = None) -> None:
        """Commit the pending loop guard state after write succeeds."""
        pending = getattr(self, "_pending_guard_state", None)
        if pending is not None:
            if fields is not None:
                allowed_set = set(fields)
                merged = dict(self.loop_guard_state)
                for key, entry in pending.items():
                    if isinstance(key, tuple) and len(key) == 2:
                        if key[1] in allowed_set:
                            merged[key] = entry
                for key in list(merged.keys()):
                    if (
                        isinstance(key, tuple)
                        and len(key) == 2
                        and key[1] in allowed_set
                        and key not in pending
                    ):
                        del merged[key]
                self.loop_guard_state = merged
            else:
                self.loop_guard_state = pending
            self._pending_guard_state = None

    def loop_guard_discard(self) -> None:
        """Discard any uncommitted pending loop guard reservations."""
        self._pending_guard_state = None

    def poll_inbound_sync_request(self) -> bool:
        """Poll pending kitsu.sync_request jobs (Requirement 4.6).

        Returns:
            True if a sync request was processed/attempted, False if none.
        """
        if self.in_drain:
            return False
        if self.processor is None:
            return False
        poll_fn = getattr(self.processor, "poll_sync_request", None)
        if not callable(poll_fn):
            return False

        has_enabled = False
        for proj in self.get_paired_projects():
            if self.settings_watcher:
                eff = self.settings_watcher.get_effective_toggles(proj)
                if eff.get("master"):
                    has_enabled = True
                    break
        if not has_enabled:
            return False

        t0 = float(self.clock())
        ran = False
        try:
            ran = bool(poll_fn())
        except Exception as exc:
            logger.warning(
                "Error during inbound sync_request poll: %s",
                redact(str(exc), self._get_secrets()),
            )
        finally:
            t1 = float(self.clock())
            self.total_sync_request_s += max(0.0, t1 - t0)
            self.last_sync_request_poll = t1
        return ran

    _poll_inbound_sync_request = poll_inbound_sync_request

    def recover_interrupted(self) -> None:
        """Count own pending/in-progress jobs at start as interrupted.

        Validates: Requirement 10.9.
        """
        if not hasattr(self.ayon_client, "get_events"):
            return
        try:
            events = self.ayon_client.get_events(
                topics=[TARGET_TOPIC],
                statuses=["in_progress", "pending"],
                fields=[
                    "id",
                    "topic",
                    "summary",
                    "status",
                    "sender",
                    "createdAt",
                    "updatedAt",
                    "dependsOn",
                    "project",
                ],
            )
            for job in events:
                if job.get("sender") == self.sender:
                    self._handle_interrupted_job(job)
        except Exception as exc:
            logger.warning(
                "Could not query interrupted jobs: %s",
                redact(str(exc), self._get_secrets()),
            )

    def _handle_interrupted_job(self, job: Dict[str, Any]) -> None:
        """Handle an own in_progress or pending job found at startup."""
        job_id = job["id"]
        summary = ensure_dict(job.get("summary"))
        attempt = int(summary.get("attempt", 1))
        now = float(self.clock())
        proj = job.get("project_name") or job.get("project")
        entity_id = summary.get("entityId", NONE_VALUE)
        kitsu_id = summary.get("kitsuId", NONE_VALUE)

        if job.get("status") == "pending":
            if attempt >= MAX_ATTEMPTS:
                reason_text = (
                    f"Retry limit exceeded after restart (attempt {attempt}/4)"
                )
                desc = describe_job(
                    DECISION_FAILED,
                    {
                        "reason": reason_text,
                        "attempt": attempt,
                        "retryable": False,
                        "entity_id": entity_id,
                        "kitsu_id": kitsu_id,
                        "category": "task_status",
                        "unwritten": summary.get("notWritten", []),
                    },
                )
                self._update_event_safe(
                    job_id,
                    status="failed",
                    description=desc,
                    summary={"attempt": attempt, "lastFailedAt": now},
                    retries=FINAL_RETRIES_VALUE,
                    project_name=proj,
                )
                self.failed_final_jobs.append(
                    {
                        "job_id": job_id,
                        "entity_id": entity_id,
                        "category": "task_status",
                    }
                )
                return
            last_failed = summary.get("lastFailedAt")
            last_failed_f = (
                to_seconds_safe(last_failed) if last_failed else now
            ) or now
            self.held_job = {
                "job": job,
                "last_failed_at": last_failed_f,
                "attempt": attempt + 1,
                "sync_request_s_at_start": self.total_sync_request_s,
            }
            return

        reason_text = f"Interrupted by a Processor stop (attempt {attempt}/4)"

        if attempt >= MAX_ATTEMPTS:
            desc = describe_job(
                DECISION_FAILED,
                {
                    "reason": reason_text,
                    "attempt": attempt,
                    "retryable": False,
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                    "category": "task_status",
                    "unwritten": summary.get("notWritten", []),
                },
            )
            self._update_event_safe(
                job_id,
                status="failed",
                description=desc,
                summary={"attempt": attempt, "lastFailedAt": now},
                retries=FINAL_RETRIES_VALUE,
                project_name=proj,
            )
            level, msg = build_log_line(
                DECISION_FAILED,
                {
                    "job_id": job_id,
                    "project_name": proj,
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                    "category": "task_status",
                    "reason": reason_text,
                    "secrets": self._get_secrets(),
                },
            )
            logger.error(msg)
            self.failed_final_jobs.append(
                {
                    "job_id": job_id,
                    "entity_id": entity_id,
                    "category": "task_status",
                }
            )
        else:
            desc = f"Failed: {reason_text}. No Kitsu field was written."
            self._update_event_safe(
                job_id,
                status="pending",
                description=desc,
                summary={"attempt": attempt, "lastFailedAt": now},
                project_name=proj,
            )
            level, msg = build_log_line(
                DECISION_FAILED,
                {
                    "job_id": job_id,
                    "project_name": proj,
                    "entity_id": entity_id,
                    "kitsu_id": kitsu_id,
                    "category": "task_status",
                    "reason": reason_text,
                    "secrets": self._get_secrets(),
                },
            )
            logger.error(msg)
            self.held_job = {
                "job": job,
                "last_failed_at": now,
                "attempt": attempt + 1,
                "sync_request_s_at_start": self.total_sync_request_s,
            }

    def reap_stale(self) -> None:
        """Fail unfinished jobs of other senders idle > 300 s (4.9, 10.9)."""
        if not hasattr(self.ayon_client, "get_events"):
            return
        try:
            events = self.ayon_client.get_events(
                topics=[TARGET_TOPIC],
                statuses=["in_progress", "pending"],
                fields=[
                    "id",
                    "topic",
                    "summary",
                    "status",
                    "sender",
                    "createdAt",
                    "updatedAt",
                    "project",
                ],
            )
            now = float(self.clock())
            for job in events:
                if job.get("sender") == self.sender:
                    continue
                updated = (
                    job.get("updatedAt")
                    or job.get("updated_at")
                    or job.get("createdAt")
                    or job.get("created_at")
                )
                if updated is None:
                    continue
                up_s = to_seconds_safe(updated)
                if up_s is None:
                    continue
                idle_s = now - up_s
                if idle_s > self.STALE_AFTER_S:
                    self._reap_job(job, now)
        except Exception as exc:
            logger.warning(
                "Could not reap stale jobs: %s",
                redact(str(exc), self._get_secrets()),
            )

    def _reap_job(self, job: Dict[str, Any], now: float) -> None:
        """Reap one stale in_progress job of another sender."""
        job_id = job["id"]
        other_sender = job.get("sender", "unknown")
        summary = ensure_dict(job.get("summary"))
        attempt = int(summary.get("attempt", 1))
        proj = job.get("project_name") or job.get("project")

        if attempt >= MAX_ATTEMPTS:
            desc = describe_job(
                DECISION_FAILED,
                {
                    "reason": (
                        f"Abandoned by {other_sender} (attempt {attempt}/4)"
                    ),
                    "attempt": attempt,
                    "retryable": False,
                },
            )
            self._update_event_safe(
                job_id,
                status="failed",
                description=desc,
                summary={"attempt": attempt, "lastFailedAt": now},
                retries=FINAL_RETRIES_VALUE,
                project_name=proj,
                sender=self.sender,
            )
        else:
            desc = (
                f"Failed: Abandoned by {other_sender} (attempt {attempt}/4)."
                f" No Kitsu field was written."
            )
            self._update_event_safe(
                job_id,
                status="failed",
                description=desc,
                summary={"attempt": attempt, "lastFailedAt": now},
                project_name=proj,
                sender=self.sender,
            )

    def _update_event_safe(self, job_id: str, **kwargs: Any) -> None:
        """Safely update event in AYON or record pending update on failure."""
        if hasattr(self.ayon_client, "update_event"):
            try:
                self.ayon_client.update_event(job_id, **kwargs)
                return
            except Exception as exc:
                logger.error(
                    "Failed to update event %s: %s",
                    job_id,
                    redact(str(exc), self._get_secrets()),
                )
        if self.pending_ayon_update is None:
            self.pending_ayon_update = {
                "job_id": job_id,
                "kwargs": dict(kwargs),
                "_delivery_retries": 0,
            }

    def retry_pending_ayon_update(self) -> bool:
        """Retry a failed final AYON update alone (Requirement 4.11).

        Returns:
            True if an update was pending and successfully cleared,
            False if retry failed or no update was pending.
        """
        if not self.pending_ayon_update:
            return False
        pending = self.pending_ayon_update
        job_id = pending["job_id"]
        if "kwargs" in pending:
            kwargs = dict(pending["kwargs"])
        else:
            kwargs = {
                k: v
                for k, v in pending.items()
                if k not in ("job_id", "_delivery_retries")
            }
        try:
            self.ayon_client.update_event(job_id, **kwargs)
            self.pending_ayon_update = None
            return True
        except Exception as exc:
            pending["_delivery_retries"] = (
                pending.get("_delivery_retries", 0) + 1
            )
            logger.warning(
                "Retrying AYON update failed: %s",
                redact(str(exc), self._get_secrets()),
            )
            return False

    def _enroll(self) -> Optional[Dict[str, Any]]:
        """Enroll one source event, excluding sync-originated ones.

        Sends the sender-type exclusion filter of Requirement 5.13 when
        the creation or deletion topics are enrolled. If the server or
        client rejects the filter, enrolls once without it and keeps
        enrolling without it; runtime origin classification then skips
        the sync-originated events instead (Q7).

        Returns:
            The enrolled job dict, or None when nothing is enrollable.
        """
        kwargs: Dict[str, Any] = {
            "source_topic": self.enrolled_topics,
            "target_topic": self.TARGET_TOPIC,
            "sender": self.sender,
            "sequential": True,
            "max_retries": self.MAX_RETRIES,
        }
        events_filter = (
            build_enroll_filter(self.enrolled_topics)
            if self.enroll_filter_supported
            else None
        )

        if hasattr(self.ayon_client, "post"):
            post_kwargs = {
                "sourceTopic": self.enrolled_topics,
                "targetTopic": self.TARGET_TOPIC,
                "sender": self.sender,
                "sequential": True,
                "maxRetries": self.MAX_RETRIES,
            }
            if events_filter is not None:
                post_kwargs["filter"] = events_filter

            try:
                resp = self.ayon_client.post("enroll", **post_kwargs)
            except Exception as post_exc:
                status = getattr(
                    getattr(post_exc, "response", None),
                    "status_code",
                    getattr(post_exc, "status_code", None),
                )
                is_filter_err = status in (400, 422) or (
                    events_filter is not None
                    and "filter" in str(post_exc).lower()
                )
                if is_filter_err and events_filter is not None:
                    self.enroll_filter_supported = False
                    logger.warning(
                        "Enroll rejected events_filter (%s); enrolling "
                        "without it and relying on runtime origin checks",
                        redact(str(post_exc), self._get_secrets()),
                    )
                    post_kwargs.pop("filter", None)
                    try:
                        resp = self.ayon_client.post("enroll", **post_kwargs)
                    except Exception as fallback_exc:
                        self.last_enroll_error = fallback_exc
                        raise fallback_exc from None
                else:
                    self.last_enroll_error = post_exc
                    raise

            if hasattr(resp, "status_code"):
                if resp.status_code == 204:
                    return None
                if (
                    resp.status_code in (400, 422)
                    and events_filter is not None
                ):
                    self.enroll_filter_supported = False
                    logger.warning(
                        "Enroll rejected events_filter (HTTP %s); enrolling "
                        "without it and relying on runtime origin checks",
                        resp.status_code,
                    )
                    post_kwargs.pop("filter", None)
                    try:
                        resp2 = self.ayon_client.post("enroll", **post_kwargs)
                    except Exception as fallback_exc:
                        self.last_enroll_error = fallback_exc
                        raise fallback_exc from None
                    if hasattr(resp2, "status_code"):
                        if resp2.status_code == 204:
                            return None
                        if resp2.status_code in (200, 201):
                            return getattr(resp2, "data", None)
                        err = RuntimeError(
                            f"Enroll failed: HTTP {resp2.status_code}"
                        )
                        self.last_enroll_error = err
                        raise err
                    return getattr(resp2, "data", None)
                if resp.status_code >= 400:
                    err = RuntimeError(
                        f"Enroll failed: HTTP {resp.status_code}"
                    )
                    self.last_enroll_error = err
                    raise err
                return getattr(resp, "data", None)
            return getattr(resp, "data", None)

        try:
            return self.ayon_client.enroll_event_job(
                events_filter=events_filter, **kwargs
            )
        except Exception as filter_exc:
            if events_filter is not None:
                try:
                    job = self.ayon_client.enroll_event_job(**kwargs)
                except Exception as fallback_exc:
                    self.last_enroll_error = fallback_exc
                    raise fallback_exc from None
                self.enroll_filter_supported = False
                logger.warning(
                    "Enroll rejected events_filter (%s); enrolling without "
                    "it and relying on runtime origin checks",
                    redact(str(filter_exc), self._get_secrets()),
                )
                return job
            self.last_enroll_error = filter_exc
            raise

    def poll_once(self) -> bool:
        """Enroll and process at most one job or retry pending update.

        Returns:
            True if an attempt ran, False otherwise.
        """
        now = float(self.clock())

        # 1. Retry pending AYON update alone if one failed previously
        if self.pending_ayon_update:
            if not self.retry_pending_ayon_update():
                return False

        # Ensure gate history is loaded before enrolling or processing jobs
        if self.gate_history is not None and not getattr(
            self.gate_history, "loaded", True
        ):
            try:
                self.gate_history.load(started_at=now)
            except Exception as exc:
                self.last_enroll_error = exc
                logger.warning(
                    "Gate history load failed before poll: %s",
                    redact(str(exc), self._get_secrets()),
                )
                return False

        # 2. Check retry hold
        if self.held_job:
            hold_start_sync_s = self.held_job.get(
                "sync_request_s_at_start", 0.0
            )
            excluded_s = max(
                0.0, self.total_sync_request_s - hold_start_sync_s
            )
            due_res = retry_due(
                self.held_job["last_failed_at"],
                now,
                excluded_s,
            )
            if due_res["due"]:
                held = self.held_job
                self.held_job = None
                return self._process_job(held["job"], attempt=held["attempt"])
            else:
                # Poll sync_request while waiting (Requirement 4.6)
                if now - self.last_sync_request_poll >= 5.0:
                    self._poll_inbound_sync_request()
                return False

        # 3. Enroll job
        job = None
        if hasattr(self.ayon_client, "enroll_event_job"):
            try:
                job = self._enroll()
                self.last_enroll_error = None
            except Exception as exc:
                self.last_enroll_error = exc
                logger.warning(
                    "Enroll event job failed: %s",
                    redact(str(exc), self._get_secrets()),
                )
                return False

        if not job:
            if now - self.last_sync_request_poll >= 5.0:
                self._poll_inbound_sync_request()
            return False

        job_id = job.get("id")
        if job_id and hasattr(self.ayon_client, "get_event"):
            try:
                full_job = self.ayon_client.get_event(job_id)
                if isinstance(full_job, dict) and full_job:
                    merged = dict(full_job)
                    if job.get("status"):
                        merged["status"] = job["status"]
                    if not merged.get("dependsOn") and merged.get(
                        "depends_on"
                    ):
                        merged["dependsOn"] = merged["depends_on"]
                    if not merged.get("depends_on") and merged.get(
                        "dependsOn"
                    ):
                        merged["depends_on"] = merged["dependsOn"]
                    if not merged.get("project_name") and merged.get(
                        "project"
                    ):
                        merged["project_name"] = merged["project"]
                    if not merged.get("project") and merged.get(
                        "project_name"
                    ):
                        merged["project"] = merged["project_name"]
                    if "summary" in merged:
                        merged["summary"] = ensure_dict(merged["summary"])
                    job = merged
            except Exception as exc:
                if getattr(self, "in_drain", False):
                    self.last_enroll_error = exc
                    raise
                logger.warning(
                    "Could not fetch full event for job %s: %s",
                    job_id,
                    redact(str(exc), self._get_secrets()),
                )

        # Step 0: Check enroll status
        if (
            job.get("status") == "in_progress"
            and job.get("sender") == self.sender
        ):
            self._handle_interrupted_job(job)
            return True

        summary = job.get("summary") or {}
        last_failed_at = summary.get("lastFailedAt")
        attempt = summary.get("attempt", 1)
        if last_failed_at is not None:
            last_failed_f = to_seconds_safe(last_failed_at) or 0.0
            due_res = retry_due(last_failed_f, now, 0.0)
            if not due_res["due"]:
                self.held_job = {
                    "job": job,
                    "last_failed_at": last_failed_f,
                    "attempt": attempt + 1,
                    "sync_request_s_at_start": self.total_sync_request_s,
                }
                return False
            attempt = attempt + 1

        ran = self._process_job(job, attempt=attempt)
        self._poll_inbound_sync_request()
        return ran

    def drain(self) -> List[Dict[str, Any]]:
        """Process until nothing is enrollable and no job is held (10.5).

        Returns:
            List of jobs that failed on their last allowed attempt.
        """
        self.in_drain = True
        try:
            self.failed_final_jobs = []
            self.last_enroll_error = None
            self.reap_stale()
            self.recover_interrupted()

            last_refresh = float(self.clock())
            last_reap = float(self.clock())
            while True:
                now = float(self.clock())
                if (
                    hasattr(self, "settings_watcher")
                    and self.settings_watcher is not None
                    and now - last_refresh >= 30.0
                ):
                    try:
                        self.settings_watcher.refresh()
                    except Exception as exc:
                        logger.warning(
                            "Error refreshing settings during drain: %s",
                            redact(str(exc), self._get_secrets()),
                        )
                    last_refresh = now

                if now - last_reap >= 60.0:
                    self.reap_stale()
                    last_reap = now

                ran = self.poll_once()
                if self.last_enroll_error is not None:
                    err_msg = redact(
                        str(self.last_enroll_error), self._get_secrets()
                    )
                    raise RuntimeError(
                        f"Enroll failed during drain: {err_msg}"
                    ) from None

                if (
                    not ran
                    and not self.held_job
                    and not self.pending_ayon_update
                ):
                    has_pending = False
                    if hasattr(self.ayon_client, "get_events"):
                        try:
                            evs = list(
                                self.ayon_client.get_events(
                                    topics=[self.TARGET_TOPIC],
                                    statuses=["pending", "in_progress"],
                                    fields=["id", "status"],
                                )
                            )
                            if evs:
                                has_pending = True
                        except Exception as exc:
                            err_msg = redact(str(exc), self._get_secrets())
                            raise RuntimeError(
                                "Failed querying pending jobs during drain: "
                                f"{err_msg}"
                            ) from None
                    if not has_pending:
                        break
                    time.sleep(0.05)
                elif self.pending_ayon_update and not ran:
                    retries = self.pending_ayon_update.get(
                        "_delivery_retries",
                        self.pending_ayon_update.get("retries", 0),
                    )
                    delay = min(1.0, 0.05 * (2 ** min(retries, 5)))
                    time.sleep(delay)
                elif self.held_job and not ran:
                    time.sleep(0.01)

            return list(self.failed_final_jobs)
        finally:
            self.in_drain = False

    def _start_job(self, job: Dict[str, Any], attempt: int) -> bool:
        """Mark the job in progress before making any Kitsu calls."""
        try:
            self.ayon_client.update_event(
                job["id"],
                status="in_progress",
                project_name=job.get("project_name") or job.get("project"),
                summary={"attempt": attempt},
            )
        except Exception as exc:
            logger.error(
                "Failed to set job %s in_progress: %s. No Kitsu write sent.",
                job["id"],
                redact(str(exc), self._get_secrets()),
            )
            return False
        return True

    def _load_source_event(
        self, job: Dict[str, Any], attempt: int
    ) -> Optional[Dict[str, Any]]:
        """Fetch the source event or finish the attempt if it is unreadable."""
        source_id = job.get("dependsOn")
        error = None
        try:
            event = (
                self.ayon_client.get_event(source_id) if source_id else None
            )
            if event:
                return event
        except Exception as exc:
            error = exc
            logger.error(
                "Failed to fetch source event %s: %s",
                source_id,
                redact(str(exc), self._get_secrets()),
            )

        retryable = error is not None and attempt < MAX_ATTEMPTS
        if error is None:
            reason = f"Source event {source_id} not found"
        else:
            prefix = (
                "Transient error fetching" if retryable else "Failed to fetch"
            )
            reason = f"{prefix} source event {source_id}: {error}"
        saved = ensure_dict(job.get("summary"))
        result = JobResult(
            decision=DECISION_FAILED,
            details={"reason": reason, "error": str(error) if error else ""},
            writes=list(saved.get("writes") or []),
            not_written=normalize_not_written(saved.get("notWritten")),
            retryable=retryable,
            error_kind=ERROR_UNREACHABLE if retryable else None,
        )
        self._finish_job(
            job_id=job["id"],
            result=result,
            summary={
                "sourceEventId": source_id,
                "attempt": attempt,
                "writes": result.writes,
                "notWritten": result.not_written or None,
            },
            project_name=job.get("project_name") or job.get("project"),
            attempt=attempt,
        )
        return None

    def _build_context(
        self, job: Dict[str, Any], event: Dict[str, Any], attempt: int
    ) -> JobContext:
        """Collect source identity, dependencies, and prior retry state."""
        summary = event.get("summary") or {}
        saved = ensure_dict(job.get("summary"))
        project_name = (
            job.get("project_name")
            or job.get("project")
            or event.get("project_name")
            or event.get("project")
            or summary.get("project_name")
            or summary.get("project")
        )
        return JobContext(
            event=event,
            job_id=job["id"],
            category="",
            entity_id=(
                summary.get("entityId")
                or summary.get("taskId")
                or summary.get("folderId")
                or ""
            ),
            project_name=project_name,
            effective_toggles={},
            conflict_policy="kitsu_wins",
            identity_resolver=self.identity_resolver,
            writer=self.writer,
            loop_guard_check=self.loop_guard_check,
            clock=self.clock,
            processor=self.processor,
            attempt=attempt,
            loop_guard_commit=self.loop_guard_commit,
            loop_guard_discard=self.loop_guard_discard,
            prior_writes=list(saved.get("writes") or []),
            prior_not_written=normalize_not_written(saved.get("notWritten")),
        )

    @staticmethod
    def _skip_result(
        ctx: JobContext, reason: str, **details: Any
    ) -> JobResult:
        """Retain earlier writes when a retry is skipped before dispatch."""
        return JobResult(
            decision=DECISION_SKIPPED,
            details={
                "reason": reason,
                "event_id": ctx.event.get("id"),
                "project": ctx.project_name,
                "writes": ctx.prior_writes,
                "unwritten": ctx.prior_not_written,
                **details,
            },
            writes=ctx.prior_writes,
        )

    def _check_eligibility(
        self, ctx: JobContext
    ) -> tuple[List[str], Optional[JobResult]]:
        """Resolve category, origin, pairing, and historical settings gates."""
        topic = ctx.event.get("topic", "")
        if topic in ("entity.project.deleted", "entity.user.deleted"):
            return [], self._skip_result(
                ctx, "project and person deletion is out of scope"
            )
        categories = categories_for(ctx.event)
        if not categories:
            return [], self._skip_result(ctx, f"topic {topic} is out of scope")

        ctx.category = categories[0]
        origin = classify_origin(ctx.event, ORIGIN_MARKERS)
        if origin in (ORIGIN_SYNC_ORIGINATED, ORIGIN_UNKNOWN):
            reason = (
                "sync originated"
                if origin == ORIGIN_SYNC_ORIGINATED
                else "origin unknown"
            )
            return [], self._skip_result(ctx, reason)
        if ctx.project_name not in self.get_paired_projects():
            return [], self._skip_result(
                ctx, f"project '{ctx.project_name}' is not a Paired_Project"
            )

        created_at = ctx.event.get("createdAt") or ctx.event.get("created_at")
        gate_state = (
            self.gate_history.toggles_at(ctx.project_name, created_at)
            if self.gate_history
            else {"state": "no_history", "toggles": None}
        )
        ctx.effective_toggles = (
            self.settings_watcher.get_effective_toggles(ctx.project_name)
            if self.settings_watcher
            else {"valid": True, "master": True, "categories": {}}
        )
        ctx.conflict_policy = ctx.effective_toggles.get(
            "conflict_policy", "kitsu_wins"
        )
        enabled = []
        gated = []
        for category in categories:
            decision = gate_decision(
                category, gate_state, ctx.effective_toggles
            )
            if decision["allowed"]:
                enabled.append(category)
                continue
            gated.append((category, decision))
            if (
                gate_state.get("state") == STATE_UNKNOWN_GAP
                and self.gate_history
            ):
                self.gate_history.record_gap_skip()
            if not ctx.effective_toggles.get("valid"):
                logger.error(
                    "Invalid Two_Way_Sync_Settings for project %s: %s",
                    ctx.project_name,
                    redact(
                        str(ctx.effective_toggles.get("error")),
                        self._get_secrets(),
                    ),
                )
        if not enabled:
            category, decision = gated[0]
            ctx.category = category
            return categories, self._skip_result(
                ctx, decision["reason"], gated=True, category=category
            )
        ctx.category = enabled[0]
        return enabled, None

    def _check_supersession(self, ctx: JobContext) -> Dict[str, Any]:
        """Find fields already written by jobs with newer source events."""
        fields = _retried_fields_for_job(ctx.category, ctx.event)
        if ctx.attempt <= 1:
            return supersede_fields(fields, [])
        try:
            candidates = self.ayon_client.get_events(
                topics=[self.TARGET_TOPIC],
                project_names=[ctx.project_name],
                statuses=["finished"],
                fields=[
                    "id",
                    "topic",
                    "summary",
                    "status",
                    "createdAt",
                    "dependsOn",
                    "project",
                ],
            )
            source_time = to_seconds_safe(
                ctx.event.get("createdAt") or ctx.event.get("created_at")
            )
            newer = []
            for candidate in candidates:
                summary = ensure_dict(candidate.get("summary"))
                entity_id = summary.get("entityId") or candidate.get(
                    "entityId"
                )
                if entity_id != ctx.entity_id:
                    continue
                if summary.get(
                    "category"
                ) != ctx.category and ctx.category not in (
                    summary.get("categories") or []
                ):
                    continue
                if source_time is None:
                    continue
                timestamp = summary.get("sourceCreatedAt")
                if timestamp is None and summary.get("sourceEventId"):
                    try:
                        event = self.ayon_client.get_event(
                            summary["sourceEventId"]
                        )
                        if event:
                            timestamp = event.get("createdAt") or event.get(
                                "created_at"
                            )
                    except Exception:
                        pass
                candidate_time = to_seconds_safe(timestamp)
                if candidate_time is not None and candidate_time > source_time:
                    newer.append(candidate)
            return supersede_fields(fields, newer)
        except Exception as exc:
            logger.warning(
                "Supersession check failed: %s",
                redact(str(exc), self._get_secrets()),
            )
            return supersede_fields(fields, [])

    def _process_job(self, job: Dict[str, Any], attempt: int = 1) -> bool:
        """Load, gate, dispatch, and finish a single outbound attempt."""
        if not self._start_job(job, attempt):
            return False
        event = self._load_source_event(job, attempt)
        if event is None:
            return True

        ctx = self._build_context(job, event, attempt)
        categories, result = self._check_eligibility(ctx)
        summary = {
            "sourceEventId": job.get("dependsOn"),
            "dependsOn": job.get("dependsOn"),
            "sourceUser": event.get("user") or "unknown",
            "sourceTopic": event.get("topic", ""),
            "sourceCreatedAt": event.get("createdAt")
            or event.get("created_at"),
            "entityId": ctx.entity_id or NONE_VALUE,
            "attempt": attempt,
            "categories": categories,
        }
        if result is not None:
            self._finish_result(ctx, result, summary)
            return True

        supersession = self._check_supersession(ctx)
        ctx.omitted_fields = supersession["omit"]
        if not supersession["keep"] and ctx.omitted_fields:
            result = self._skip_result(ctx, supersession["skip_reason"])
            result.omitted_by = supersession["newer_job_ids"]
            summary["omittedFields"] = ctx.omitted_fields
        else:
            self._pending_guard_state = None
            ctx.kitsu_project_id = self.get_kitsu_project_id(ctx.project_name)
            result = self._dispatch(ctx)
            result.omitted_by = (
                result.omitted_by or supersession["newer_job_ids"]
            )

        self._finish_result(ctx, result, summary)
        return True

    def _dispatch(self, ctx: JobContext) -> JobResult:
        """Run the handler, reporting unexpected exceptions as failures."""
        handler = HANDLERS.get(ctx.category)
        if handler is None:
            return failed_result(
                ctx,
                f"No handler registered for category {ctx.category}",
                writes=ctx.prior_writes,
                not_written=ctx.prior_not_written,
            )
        try:
            return handler(ctx)
        except Exception as exc:
            logger.error(
                "Unexpected exception in handler for %s: %s",
                ctx.job_id,
                redact(str(exc), self._get_secrets()),
            )
            return failed_result(
                ctx,
                f"{type(exc).__name__}: {exc}",
                error=str(exc),
                writes=ctx.prior_writes,
                not_written=ctx.prior_not_written,
            )

    def _finish_result(
        self, ctx: JobContext, result: JobResult, summary: Dict[str, Any]
    ) -> None:
        """Merge write history and finish the structured handler outcome."""
        saved_writes = result.writes or ctx.prior_writes
        not_written = result.not_written
        if result.decision == DECISION_FAILED:
            not_written = not_written or ctx.prior_not_written
        summary.update(
            {
                "entityType": result.entity_type or "task",
                "kitsuId": result.kitsu_id or NONE_VALUE,
                "decision": result.decision,
                "writes": saved_writes,
                "notWritten": not_written or None,
                "omittedBy": result.omitted_by,
            }
        )
        self._finish_job(
            job_id=ctx.job_id,
            result=result,
            summary=summary,
            project_name=ctx.project_name,
            attempt=ctx.attempt,
            entity_id=ctx.entity_id,
            category=ctx.category,
        )

    def _finish_job(
        self,
        job_id: str,
        result: JobResult,
        summary: Dict[str, Any],
        project_name: Optional[str] = None,
        attempt: int = 1,
        entity_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> None:
        """Persist the outcome, schedule retries, and emit one log entry."""
        self._pending_guard_state = None
        now = float(self.clock())
        decision = result.decision
        retryable = (
            decision == DECISION_FAILED
            and result.retryable
            and attempt < MAX_ATTEMPTS
        )
        details = dict(result.details)
        retries_value = None

        if decision == DECISION_FAILED:
            summary.update(
                {
                    "lastFailedAt": now,
                    "errorKind": result.error_kind,
                    "httpStatus": result.http_status,
                    "attempt": attempt,
                }
            )
            details.update(
                {
                    "entity_id": entity_id,
                    "kitsu_id": result.kitsu_id,
                    "category": category,
                    "attempt": attempt,
                    "retryable": retryable,
                    "error_kind": result.error_kind,
                    "http_status": result.http_status,
                    "writes": summary.get("writes") or [],
                    "unwritten": summary.get("notWritten") or None,
                }
            )
            if attempt >= MAX_ATTEMPTS:
                label = result.error_kind or "retry limit exceeded"
                if result.http_status:
                    label = f"{label} [HTTP {result.http_status}]"
                terminal_meta = f"{label} (attempt {attempt}/{MAX_ATTEMPTS})"
                reason = str(details.get("reason") or "").strip()
                details["reason"] = (
                    f"{reason}, {terminal_meta}"
                    if reason
                    and reason not in terminal_meta
                    and reason.lower() not in ("failure", "failed")
                    else terminal_meta
                )

        if retryable:
            status = "pending"
            self.held_job = {
                "job": {
                    "id": job_id,
                    "project_name": project_name,
                    "summary": dict(summary),
                    "dependsOn": summary.get("sourceEventId"),
                },
                "last_failed_at": now,
                "attempt": attempt + 1,
                "sync_request_s_at_start": self.total_sync_request_s,
            }
        else:
            status = "failed" if decision == DECISION_FAILED else "finished"
            if decision == DECISION_FAILED:
                retries_value = FINAL_RETRIES_VALUE
                self.failed_final_jobs.append(
                    {
                        "job_id": job_id,
                        "entity_id": entity_id,
                        "category": category,
                    }
                )

        if category and "category" not in summary:
            summary["category"] = category

        description = describe_job(decision, details)
        secrets = self._get_secrets()
        if secrets:
            description = redact(description, secrets)
            for key, value in list(summary.items()):
                if isinstance(value, str):
                    summary[key] = redact(value, secrets)

        update_kwargs: Dict[str, Any] = {
            "status": status,
            "description": description,
            "summary": summary,
            "project_name": project_name,
        }
        if retries_value is not None:
            update_kwargs["retries"] = retries_value
        self._update_event_safe(job_id, **update_kwargs)

        level, message = build_log_line(
            decision,
            {
                "job_id": job_id,
                "project_name": project_name,
                "entity_id": entity_id,
                "kitsu_id": result.kitsu_id,
                "category": category,
                "secrets": secrets,
            },
        )
        logger.log(getattr(logging, level), message)

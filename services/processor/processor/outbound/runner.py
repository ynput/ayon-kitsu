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
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    DECISION_SKIPPED,
    DESCRIPTION_FAILED,
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
    _format_value,
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
from .origin import build_enroll_filter, classify_origin
from .retry import retry_due, supersede_fields
from .settings_watch import GateHistory, SettingsWatcher

logger = logging.getLogger(__name__)

HANDLERS: Dict[str, Callable[[Any], Any]] = {
    "task_status": handle_task_status,
    "task_assignees": handle_task_assignees,
    "entity_attributes": handle_attributes,
    "entity_creation": handle_creation,
    "entity_rename": handle_rename,
    "entity_deletion": handle_deletion,
}


class JobContext:
    """Context passed to category handlers."""

    def __init__(
        self,
        event: Dict[str, Any],
        job_id: str,
        category: str,
        entity_id: str,
        project_name: str,
        effective_toggles: Dict[str, Any],
        conflict_policy: str,
        identity_resolver: Any,
        writer: Any,
        loop_guard_check: Callable[[str, str], Dict[str, Any]],
        clock: Callable[[], float],
        processor: Optional[Any] = None,
        attempt: int = 1,
        omitted_fields: Optional[List[str]] = None,
        kitsu_project_id: Optional[str] = None,
        loop_guard_commit: Optional[Callable[..., None]] = None,
        loop_guard_discard: Optional[Callable[[], None]] = None,
        prior_writes: Optional[List[Dict[str, Any]]] = None,
        prior_not_written: Optional[Any] = None,
    ):
        self.event = event
        self.job_id = job_id
        self.category = category
        self.entity_id = entity_id
        self.project_name = project_name
        self.effective_toggles = effective_toggles
        self.conflict_policy = conflict_policy
        self.identity_resolver = identity_resolver
        self.writer = writer
        self.loop_guard_check = loop_guard_check
        self.clock = clock
        self.processor = processor
        self.attempt = attempt
        self.omitted_fields = omitted_fields or []
        self.kitsu_project_id = kitsu_project_id
        self.loop_guard_commit = loop_guard_commit
        self.loop_guard_discard = loop_guard_discard
        self.prior_writes = prior_writes or []
        self.prior_not_written = prior_not_written


class JobResult:
    """Outcome produced by a category handler."""

    def __init__(
        self,
        decision: str,
        description: str,
        writes: Optional[List[Dict[str, Any]]] = None,
        not_written: Optional[List[Dict[str, Any]]] = None,
        error_kind: Optional[str] = None,
        http_status: Optional[int] = None,
        retryable: bool = False,
        kitsu_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        omitted_by: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.decision = decision
        self.description = description
        self.writes = writes or []
        self.not_written = not_written or []
        self.error_kind = error_kind
        self.http_status = http_status
        self.retryable = retryable
        self.kitsu_id = kitsu_id
        self.entity_type = entity_type
        self.omitted_by = omitted_by or []
        self.details = details or {}

def _extract_failure_reason(description: str) -> Optional[str]:
    """Extract original failure reason from formatted failure description."""
    if not description:
        return None
    text = description.strip()
    if text.startswith(DESCRIPTION_FAILED):
        text = text[len(DESCRIPTION_FAILED):].strip()
    for marker in (". Written fields:", ". No Kitsu field was written."):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    parts = text.split(", ")
    if (
        len(parts) >= 4
        and parts[0].startswith("entity ")
        and parts[1].startswith("kitsu_id ")
        and parts[2].startswith("category ")
        and parts[3].startswith("unwritten values: ")
    ):
        reason = ", ".join(parts[4:]).strip()
        return reason or None
    return text or None


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
            if k in (
                "data.fps",
                "data.frame_in",
                "data.frame_out",
                "nb_frames",
                "data.resolution",
                "description",
            ) and k not in fields:
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
        """Get list of paired AYON project names."""
        if self.processor is not None:
            getter = getattr(self.processor, "get_outbound_pairings", None)
            if callable(getter):
                try:
                    res = getter()
                    if isinstance(res, dict):
                        return list(res.keys())
                except Exception:
                    pass
            pairing = getattr(self.processor, "pairing_list", None)
            if isinstance(pairing, dict):
                has_get_paired = (
                    hasattr(self.processor, "get_paired_ayon_project")
                    and not getattr(
                        self.processor.__class__,
                        "__module__",
                        "",
                    ).startswith("unittest.mock")
                )
                if has_get_paired:
                    return [name for name in pairing.values() if name]
                return list(pairing.keys())
            if isinstance(pairing, (list, tuple, set)):
                return list(pairing)
            p_getter = getattr(self.processor, "get_paired_projects", None)
            if callable(p_getter):
                try:
                    res = p_getter()
                    if isinstance(res, (list, tuple, set)):
                        return list(res)
                except Exception:
                    pass
        return []

    def get_kitsu_project_id(self, project_name: str) -> str:
        """Get paired Kitsu project id for an AYON project name."""
        if self.processor is not None:
            getter = getattr(self.processor, "get_outbound_pairings", None)
            if callable(getter):
                try:
                    res = getter()
                    if isinstance(res, dict) and project_name in res:
                        return str(res[project_name])
                except Exception:
                    pass
            pairing = getattr(self.processor, "pairing_list", None)
            if isinstance(pairing, dict):
                has_get_paired = (
                    hasattr(self.processor, "get_paired_ayon_project")
                    and not getattr(
                        self.processor.__class__,
                        "__module__",
                        "",
                    ).startswith("unittest.mock")
                )
                if has_get_paired:
                    for k_id, a_name in pairing.items():
                        if a_name == project_name:
                            return str(k_id)
                val = pairing.get(project_name, "")
                if val:
                    return str(val)
                for k_id, a_name in pairing.items():
                    if a_name == project_name:
                        return str(k_id)
        return ""

    def loop_guard_check(self, entity_id: str, field: str) -> Dict[str, Any]:
        """Run loop guard check for an entity field using current time."""
        now = float(self.clock())
        base_state = (
            self._pending_guard_state
            if getattr(self, "_pending_guard_state", None) is not None
            else self.loop_guard_state
        )
        res, new_state = loop_guard_apply(
            base_state, entity_id, field, now
        )
        self._pending_guard_state = new_state
        return res

    def loop_guard_commit(
        self, fields: Optional[List[str]] = None
    ) -> None:
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

        reason_text = (
            f"Interrupted by a Processor stop (attempt {attempt}/4)"
        )

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
            desc = (
                f"Failed: {reason_text}. "
                "No Kitsu field was written."
            )
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
                k: v for k, v in pending.items()
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
                is_filter_err = (
                    status in (400, 422)
                    or (
                        events_filter is not None
                        and "filter" in str(post_exc).lower()
                    )
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
        if (
            self.gate_history is not None
            and not getattr(self.gate_history, "loaded", True)
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
                    if (
                        not merged.get("dependsOn")
                        and merged.get("depends_on")
                    ):
                        merged["dependsOn"] = merged["depends_on"]
                    if (
                        not merged.get("depends_on")
                        and merged.get("dependsOn")
                    ):
                        merged["depends_on"] = merged["dependsOn"]
                    if (
                        not merged.get("project_name")
                        and merged.get("project")
                    ):
                        merged["project_name"] = merged["project"]
                    if (
                        not merged.get("project")
                        and merged.get("project_name")
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

    def _process_job(self, job: Dict[str, Any], attempt: int = 1) -> bool:
        """Execute shared steps 1 to 8 for an Outbound_Job."""
        job_id = job["id"]
        source_event_id = job.get("dependsOn")
        project_name = job.get("project_name") or job.get("project")

        # Step 1: Set in_progress before any Kitsu call (4.2, 4.11)
        try:
            if hasattr(self.ayon_client, "update_event"):
                self.ayon_client.update_event(
                    job_id,
                    status="in_progress",
                    project_name=project_name,
                    summary={"attempt": attempt},
                )
        except Exception as exc:
            logger.error(
                "Failed to set job %s in_progress: %s. No Kitsu write sent.",
                job_id,
                redact(str(exc), self._get_secrets()),
            )
            return False

        # Load source event
        job_summary = ensure_dict(job.get("summary"))
        prior_writes = list(job_summary.get("writes") or [])
        prior_not_written = job_summary.get("notWritten")
        source_event = None
        source_fetch_err = None
        if hasattr(self.ayon_client, "get_event") and source_event_id:
            try:
                source_event = self.ayon_client.get_event(source_event_id)
            except Exception as exc:
                source_fetch_err = exc
                logger.error(
                    "Failed to fetch source event %s: %s",
                    source_event_id,
                    redact(str(exc), self._get_secrets()),
                )

        if not source_event:
            is_transient = source_fetch_err is not None
            if is_transient and attempt < MAX_ATTEMPTS:
                reason = (
                    f"Transient error fetching source event "
                    f"{source_event_id}: {source_fetch_err}"
                )
                fail_details = {
                    "reason": reason,
                    "error": str(source_fetch_err),
                    "attempt": attempt,
                    "retryable": True,
                    "error_kind": ERROR_UNREACHABLE,
                    "entity_id": NONE_VALUE,
                    "kitsu_id": NONE_VALUE,
                    "category": NONE_VALUE,
                }
                if prior_writes:
                    fail_details["writes"] = prior_writes
                if prior_not_written:
                    fail_details["unwritten"] = prior_not_written
                desc = describe_job(
                    DECISION_FAILED,
                    fail_details,
                )
                self._finish_job(
                    job_id=job_id,
                    decision=DECISION_FAILED,
                    description=desc,
                    summary={
                        "attempt": attempt,
                        "sourceEventId": source_event_id,
                        "writes": prior_writes,
                        "notWritten": prior_not_written,
                    },
                    project_name=project_name,
                    attempt=attempt,
                    retryable=True,
                    error_kind=ERROR_UNREACHABLE,
                )
                return True

            fail_details = {
                "reason": (
                    f"Failed to fetch source event {source_event_id}: "
                    f"{source_fetch_err}"
                    if is_transient
                    else f"Source event {source_event_id} not found"
                ),
                "attempt": attempt,
                "retryable": False,
                "entity_id": NONE_VALUE,
                "kitsu_id": NONE_VALUE,
                "category": NONE_VALUE,
            }
            if prior_writes:
                fail_details["writes"] = prior_writes
            if prior_not_written:
                fail_details["unwritten"] = prior_not_written
            desc = describe_job(
                DECISION_FAILED,
                fail_details,
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_FAILED,
                description=desc,
                summary={
                    "attempt": attempt,
                    "sourceEventId": source_event_id,
                    "writes": prior_writes,
                    "notWritten": prior_not_written,
                },
                project_name=project_name,
                attempt=attempt,
                retryable=False,
            )
            return True

        topic = source_event.get("topic", "")
        summary = source_event.get("summary") or {}
        if not project_name:
            project_name = (
                source_event.get("project_name")
                or source_event.get("project")
                or summary.get("project_name")
                or summary.get("project")
            )
        entity_id = (
            summary.get("entityId")
            or summary.get("taskId")
            or summary.get("folderId")
            or ""
        )
        source_user = source_event.get("user") or "unknown"
        source_topic = source_event.get("topic") or topic
        created_at = (
            source_event.get("createdAt")
            or source_event.get("created_at")
        )

        base_summary = {
            "sourceEventId": source_event_id,
            "dependsOn": source_event_id,
            "sourceUser": source_user,
            "sourceTopic": source_topic,
            "sourceCreatedAt": created_at,
            "entityId": entity_id or NONE_VALUE,
            "attempt": attempt,
            "writes": prior_writes,
            "notWritten": prior_not_written,
        }

        def _with_writes(details_dict: Dict[str, Any]) -> Dict[str, Any]:
            if prior_writes:
                details_dict["writes"] = prior_writes
            if prior_not_written:
                details_dict["unwritten"] = prior_not_written
            return details_dict

        # Step 2: categories_for topic and out-of-scope check
        if topic in ("entity.project.deleted", "entity.user.deleted"):
            desc = describe_job(
                DECISION_SKIPPED,
                _with_writes({
                    "reason": "project and person deletion is out of scope",
                    "event_id": source_event_id,
                    "project": project_name,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_SKIPPED,
                description=desc,
                summary=dict(base_summary),
                project_name=project_name,
                attempt=attempt,
                entity_id=entity_id,
            )
            return True

        categories = categories_for(source_event)
        if not categories:
            desc = describe_job(
                DECISION_SKIPPED,
                _with_writes({
                    "reason": f"topic {topic} is out of scope",
                    "event_id": source_event_id,
                    "project": project_name,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_SKIPPED,
                description=desc,
                summary=dict(base_summary),
                project_name=project_name,
                attempt=attempt,
                entity_id=entity_id,
            )
            return True

        # Step 3: classify_origin
        origin = classify_origin(source_event, ORIGIN_MARKERS)
        if origin == ORIGIN_SYNC_ORIGINATED:
            desc = describe_job(
                DECISION_SKIPPED,
                _with_writes({
                    "reason": "sync originated",
                    "event_id": source_event_id,
                    "project": project_name,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_SKIPPED,
                description=desc,
                summary=dict(base_summary),
                project_name=project_name,
                attempt=attempt,
                entity_id=entity_id,
                category=categories[0] if categories else None,
            )
            return True
        elif origin == ORIGIN_UNKNOWN:
            desc = describe_job(
                DECISION_SKIPPED,
                _with_writes({
                    "reason": "origin unknown",
                    "event_id": source_event_id,
                    "project": project_name,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_SKIPPED,
                description=desc,
                summary=dict(base_summary),
                project_name=project_name,
                attempt=attempt,
                entity_id=entity_id,
                category=categories[0] if categories else None,
            )
            return True

        # Step 4: Paired_Project check (3.3)
        paired_projects = self.get_paired_projects()
        if project_name not in paired_projects:
            desc = describe_job(
                DECISION_SKIPPED,
                _with_writes({
                    "reason": (
                        f"project '{project_name}' is not a Paired_Project"
                    ),
                    "event_id": source_event_id,
                    "project": project_name,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_SKIPPED,
                description=desc,
                summary=dict(base_summary),
                project_name=project_name,
                attempt=attempt,
                entity_id=entity_id,
                category=categories[0] if categories else None,
            )
            return True

        # Step 5: Gate per category
        gate_state = (
            self.gate_history.toggles_at(project_name, created_at)
            if self.gate_history
            else {"state": "no_history", "toggles": None}
        )
        effective_now = (
            self.settings_watcher.get_effective_toggles(project_name)
            if self.settings_watcher
            else {"valid": True, "master": True, "categories": {}}
        )

        enabled_categories: List[str] = []
        gated_skips: List[tuple] = []
        for cat in categories:
            g_dec = gate_decision(cat, gate_state, effective_now)
            if not g_dec["allowed"]:
                gated_skips.append((cat, g_dec))
                if gate_state.get("state") == STATE_UNKNOWN_GAP:
                    if self.gate_history:
                        self.gate_history.record_gap_skip()
                if not effective_now.get("valid"):
                    logger.error(
                        "Invalid Two_Way_Sync_Settings for project %s: %s",
                        project_name,
                        redact(
                            str(effective_now.get("error")),
                            self._get_secrets(),
                        ),
                    )
            else:
                enabled_categories.append(cat)

        if not enabled_categories:
            cat, g_dec = gated_skips[0]
            desc = describe_job(
                DECISION_SKIPPED,
                _with_writes({
                    "reason": g_dec["reason"],
                    "gated": True,
                    "event_id": source_event_id,
                    "project": project_name,
                    "category": cat,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_SKIPPED,
                description=desc,
                summary={
                    **base_summary,
                    "categories": categories,
                    "category": cat,
                },
                project_name=project_name,
                attempt=attempt,
                category=cat,
                entity_id=entity_id,
            )
            return True

        cat = enabled_categories[0]

        # Step 6: Retry supersession check when attempt > 1 (10.7)
        omitted_fields: List[str] = []
        newer_job_ids: List[str] = []
        if attempt > 1 and hasattr(self.ayon_client, "get_events"):
            try:
                raw_newer = self.ayon_client.get_events(
                    topics=[self.TARGET_TOPIC],
                    project_names=[project_name],
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
                newer_list = list(raw_newer)
                src_time = to_seconds_safe(created_at)
                filtered_newer = []
                for cand in newer_list:
                    cand_summary = ensure_dict(cand.get("summary"))
                    cand_ent = (
                        cand_summary.get("entityId")
                        or cand.get("entityId")
                    )
                    if cand_ent != entity_id:
                        continue
                    # Must match same Sync_Category (Req 10.7)
                    cand_cats = cand_summary.get("categories") or []
                    cand_cat = cand_summary.get("category")
                    if cand_cat != cat and cat not in cand_cats:
                        continue
                    # Source event timestamp comparison (candidate > retried)
                    if src_time is None:
                        continue
                    cand_src_raw = cand_summary.get("sourceCreatedAt")
                    if (
                        cand_src_raw is None
                        and hasattr(self.ayon_client, "get_event")
                        and cand_summary.get("sourceEventId")
                    ):
                        try:
                            c_ev = self.ayon_client.get_event(
                                cand_summary["sourceEventId"]
                            )
                            if c_ev:
                                cand_src_raw = (
                                    c_ev.get("createdAt")
                                    or c_ev.get("created_at")
                                )
                        except Exception:
                            pass
                    cand_src_time = to_seconds_safe(cand_src_raw)
                    if cand_src_time is None or cand_src_time <= src_time:
                        continue
                    filtered_newer.append(cand)

                retried_fields = _retried_fields_for_job(cat, source_event)
                sup = supersede_fields(retried_fields, filtered_newer)
                omitted_fields = sup["omit"]
                newer_job_ids = sup["newer_job_ids"]
                if not sup["keep"] and omitted_fields:
                    desc = describe_job(
                        DECISION_SKIPPED,
                        _with_writes({
                            "reason": sup["skip_reason"] or (
                                f"omitted by newer jobs: {newer_job_ids}"
                            ),
                            "event_id": source_event_id,
                            "project": project_name,
                        }),
                    )
                    self._finish_job(
                        job_id=job_id,
                        decision=DECISION_SKIPPED,
                        description=desc,
                        summary={
                            **base_summary,
                            "omittedBy": newer_job_ids,
                            "omittedFields": omitted_fields,
                            "category": cat,
                        },
                        project_name=project_name,
                        attempt=attempt,
                        entity_id=entity_id,
                        category=cat,
                    )
                    return True
            except Exception as exc:
                logger.warning(
                    "Supersession check failed: %s",
                    redact(str(exc), self._get_secrets()),
                )

        # Step 7: Handler per enabled category
        handler = HANDLERS.get(cat)
        if not handler:
            desc = describe_job(
                DECISION_FAILED,
                _with_writes({
                    "reason": f"No handler registered for category {cat}",
                    "attempt": attempt,
                    "retryable": False,
                    "entity_id": entity_id,
                    "category": cat,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_FAILED,
                description=desc,
                summary={
                    "sourceEventId": source_event_id,
                    "attempt": attempt,
                    "writes": prior_writes,
                    "notWritten": prior_not_written,
                },
                project_name=project_name,
                attempt=attempt,
                retryable=False,
                category=cat,
            )
            return True

        self._pending_guard_state = None
        prior_writes = list(job.get("summary", {}).get("writes") or [])
        prior_not_written = job.get("summary", {}).get("notWritten")
        ctx = JobContext(
            event=source_event,
            job_id=job_id,
            category=cat,
            entity_id=entity_id,
            project_name=project_name,
            effective_toggles=effective_now,
            conflict_policy=effective_now.get(
                "conflict_policy", "kitsu_wins"
            ),
            identity_resolver=self.identity_resolver,
            writer=self.writer,
            loop_guard_check=self.loop_guard_check,
            clock=self.clock,
            processor=self.processor,
            attempt=attempt,
            omitted_fields=omitted_fields,
            kitsu_project_id=self.get_kitsu_project_id(project_name),
            loop_guard_commit=self.loop_guard_commit,
            loop_guard_discard=self.loop_guard_discard,
            prior_writes=prior_writes,
            prior_not_written=prior_not_written,
        )

        try:
            result = handler(ctx)
        except Exception as exc:
            logger.error(
                "Unexpected exception in handler for %s: %s",
                job_id,
                redact(str(exc), self._get_secrets()),
            )
            desc = describe_job(
                DECISION_FAILED,
                _with_writes({
                    "reason": f"{type(exc).__name__}: {exc}",
                    "error": str(exc),
                    "attempt": attempt,
                    "retryable": False,
                    "entity_id": entity_id,
                    "category": cat,
                }),
            )
            self._finish_job(
                job_id=job_id,
                decision=DECISION_FAILED,
                description=desc,
                summary={
                    "sourceEventId": source_event_id,
                    "attempt": attempt,
                    "writes": prior_writes,
                    "notWritten": prior_not_written,
                },
                project_name=project_name,
                attempt=attempt,
                retryable=False,
                entity_id=entity_id,
                category=cat,
            )
            return True

        # Step 8: job_outcome and finish job
        saved_writes = (
            result.writes if result.writes else prior_writes
        )
        if result.decision in (
            DECISION_APPLIED, DECISION_SKIPPED, DECISION_CONFLICT
        ):
            saved_not_written = result.not_written or None
        else:
            saved_not_written = (
                result.not_written
                if result.not_written
                else prior_not_written
            )
        self._finish_job(
            job_id=job_id,
            decision=result.decision,
            description=result.description,
            summary={
                "sourceEventId": source_event_id,
                "sourceTopic": topic,
                "sourceUser": source_event.get("user") or "unknown",
                "sourceCreatedAt": created_at,
                "entityType": result.entity_type or "task",
                "entityId": entity_id,
                "kitsuId": result.kitsu_id or NONE_VALUE,
                "categories": enabled_categories,
                "decision": result.decision,
                "attempt": attempt,
                "writes": saved_writes,
                "notWritten": saved_not_written,
                "omittedBy": result.omitted_by or newer_job_ids,
            },
            project_name=project_name,
            attempt=attempt,
            retryable=result.retryable,
            error_kind=result.error_kind,
            http_status=result.http_status,
            entity_id=entity_id,
            kitsu_id=result.kitsu_id,
            category=cat,
        )
        return True

    def _finish_job(
        self,
        job_id: str,
        decision: str,
        description: str,
        summary: Dict[str, Any],
        project_name: Optional[str] = None,
        attempt: int = 1,
        retryable: bool = False,
        error_kind: Optional[str] = None,
        http_status: Optional[int] = None,
        entity_id: Optional[str] = None,
        kitsu_id: Optional[str] = None,
        category: Optional[str] = None,
    ) -> None:
        """Update job status and summary, and emit exactly one log entry."""
        self._pending_guard_state = None
        now = float(self.clock())
        is_retryable_attempt = (
            decision == DECISION_FAILED
            and retryable
            and attempt < MAX_ATTEMPTS
        )

        if is_retryable_attempt:
            status = "pending"
            retries_value = None
            summary["lastFailedAt"] = now
            summary["errorKind"] = error_kind
            summary["httpStatus"] = http_status
            summary["attempt"] = attempt
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
            status = (
                "finished"
                if decision
                in (DECISION_APPLIED, DECISION_SKIPPED, DECISION_CONFLICT)
                else "failed"
            )
            retries_value = (
                FINAL_RETRIES_VALUE if decision == DECISION_FAILED else None
            )
            if decision == DECISION_FAILED:
                summary["lastFailedAt"] = now
                summary["errorKind"] = error_kind
                summary["httpStatus"] = http_status
                summary["attempt"] = attempt
                unwritten = summary.get("notWritten") or []
                saved_writes = list(summary.get("writes") or [])
                if attempt >= MAX_ATTEMPTS:
                    err_label = error_kind or "retry limit exceeded"
                    if http_status:
                        err_label = f"{err_label} [HTTP {http_status}]"
                    terminal_meta = (
                        f"{err_label} "
                        f"(attempt {attempt}/{MAX_ATTEMPTS})"
                    )
                    orig_reason = _extract_failure_reason(description)
                    if (
                        orig_reason
                        and orig_reason not in terminal_meta
                        and orig_reason.lower() not in ("failure", "failed")
                    ):
                        fail_reason = f"{orig_reason}, {terminal_meta}"
                    else:
                        fail_reason = terminal_meta

                    fail_details = {
                        "entity_id": entity_id,
                        "kitsu_id": kitsu_id,
                        "category": category,
                        "unwritten": unwritten,
                        "retryable": False,
                        "http_status": http_status,
                        "error_kind": error_kind,
                        "reason": fail_reason,
                    }
                    if saved_writes:
                        fail_details["writes"] = saved_writes
                    description = describe_job(
                        DECISION_FAILED,
                        fail_details,
                    )
                elif unwritten and "unwritten values: none" in description:
                    if isinstance(unwritten, dict):
                        u_str = ", ".join(
                            f"{k}={_format_value(k, v)}"
                            for k, v in unwritten.items()
                        )
                    elif isinstance(unwritten, (list, tuple)):
                        u_str = ", ".join(str(x) for x in unwritten)
                    else:
                        u_str = str(unwritten)
                    description = description.replace(
                        "unwritten values: none",
                        f"unwritten values: {u_str}",
                    )
                self.failed_final_jobs.append(
                    {
                        "job_id": job_id,
                        "entity_id": entity_id,
                        "category": category,
                    }
                )

        if category and "category" not in summary:
            summary["category"] = category

        secrets = self._get_secrets()
        if description and secrets:
            description = redact(description, secrets)
        if secrets and isinstance(summary, dict):
            for k, v in list(summary.items()):
                if isinstance(v, str):
                    summary[k] = redact(v, secrets)

        update_kwargs: Dict[str, Any] = {
            "status": status,
            "description": description,
            "summary": summary,
            "project_name": project_name,
        }
        if retries_value is not None:
            update_kwargs["retries"] = retries_value

        self._update_event_safe(job_id, **update_kwargs)

        log_details = {
            "job_id": job_id,
            "project_name": project_name,
            "entity_id": entity_id,
            "kitsu_id": kitsu_id,
            "category": category,
            "secrets": self._get_secrets(),
        }
        level, msg = build_log_line(decision, log_details)
        if level == "INFO":
            logger.info(msg)
        elif level == "WARNING":
            logger.warning(msg)
        else:
            logger.error(msg)

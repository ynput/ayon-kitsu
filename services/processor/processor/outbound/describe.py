"""Job descriptions, log lines, redaction and latency summary (Requirement 13).

This module is part of the pure core: it imports only the standard library
and ``.constants``, takes and returns built-in values and performs no I/O
(Requirement 14.1).

It formats:

* ``describe_job``: description strings saved on ``Outbound_Job`` records,
  starting with ``Applied:``, ``Skipped:``, ``Conflict:`` or ``Failed:``
  (Requirements 4.3, 4.4, 9.4, 9.5, 10.1, 10.6, 12.4, 13.2, 13.3;
  Property 25).
* ``build_log_line``: the single log entry emitted per processing attempt,
  with level INFO, WARNING or ERROR (Requirement 13.1; Property 25).
* ``redact``: strips secrets (passwords, tokens, API keys) from text
  (Requirement 13.6; Property 26).
* ``latency_summary``: min, median, p95, max and timeout counts over measured
  samples (Requirement 1.5).
* ``status_comment_text``: the Kitsu status comment text (Requirements 6.4,
  6.9; Property 13).
"""

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .constants import (
    CONFLICT_POLICY_AYON_WINS,
    CONFLICT_POLICY_KITSU_WINS,
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    DECISION_SKIPPED,
    DESCRIPTION_APPLIED,
    DESCRIPTION_CONFLICT,
    DESCRIPTION_FAILED,
    DESCRIPTION_SKIPPED,
    MAX_ATTEMPTS,
    NONE_VALUE,
)

#: Fields whose list values are unordered sets of person ids.
UNORDERED_FIELDS = frozenset(("assignees",))

#: Text required on every skipped, kitsu_wins conflict and failed description
#: (Requirements 4.4, 13.3; Property 25).
NO_KITSU_FIELD_WRITTEN = "no Kitsu field was written"

#: Log levels for decisions (Requirement 13.1; Property 25).
DECISION_LOG_LEVELS = {
    DECISION_APPLIED: "INFO",
    DECISION_SKIPPED: "INFO",
    DECISION_CONFLICT: "WARNING",
    DECISION_FAILED: "ERROR",
}


# ---------------------------------------------------------------------------
# Comment text and redaction
# ---------------------------------------------------------------------------


def status_comment_text(
    status_name: str, username: Optional[str] = None
) -> str:
    """Build the text of the Kitsu status comment (Requirements 6.4, 6.9).

    Args:
        status_name: AYON task status name.
        username: AYON username that made the change, or None if unknown.

    Returns:
        The formatted comment string.
    """
    if username:
        return f"[AYON] Status set to '{status_name}' by {username}."
    return f"[AYON] Status set to '{status_name}' in AYON with no known user."


def redact(text: str, secrets: Optional[Iterable[str]] = None) -> str:
    """Exclude secrets from text (Requirement 13.6; Property 26).

    Args:
        text: Input string.
        secrets: Secrets to redact (passwords, tokens, API keys).

    Returns:
        Text with all occurrences of non-empty secrets replaced with a
        placeholder that contains none of the secrets.
    """
    if not text or not secrets:
        return text

    valid_secrets = sorted(
        {str(s) for s in secrets if s},
        key=len,
        reverse=True,
    )
    if not valid_secrets:
        return text

    all_chars = set().union(*valid_secrets)

    # Standard candidate placeholders in order of preference
    candidates = [
        "[REDACTED]",
        "<redacted>",
        "***REDACTED***",
        "***SECRET***",
    ]
    placeholder = None
    for cand in candidates:
        if not any(s in cand for s in valid_secrets) and not any(
            c in all_chars for c in cand
        ):
            placeholder = cand
            break

    if placeholder is None:
        # Pick a character that never appears in any secret
        chosen_char = None
        for code in list(range(33, 127)) + list(range(160, 1000)):
            char = chr(code)
            if char not in all_chars:
                chosen_char = char
                break
        if chosen_char is None:
            chosen_char = "\ufffd"
        placeholder = chosen_char * 8

    # Single-pass regex substitution with longest secrets first
    pattern = re.compile("|".join(re.escape(s) for s in valid_secrets))
    result = pattern.sub(placeholder, str(text))

    # Safety check: if any secret still appears, do a loop-safe replace
    if any(s in result for s in valid_secrets):
        for s in valid_secrets:
            if s in result:
                result = result.replace(s, placeholder)

    # In case of adversarial secondary synthesis, fall back to placeholder
    if any(s in result for s in valid_secrets):
        return placeholder

    return result


# ---------------------------------------------------------------------------
# Latency summary
# ---------------------------------------------------------------------------


def latency_summary(
    samples_ms: List[float], timeouts: int = 0
) -> Dict[str, Any]:
    """Summarize latency measurements in milliseconds (Requirement 1.5).

    Args:
        samples_ms: Measured latencies in milliseconds.
        timeouts: Count of changes not readable within 60 seconds.

    Returns:
        Dict with count, min, median, p95, max and timeouts.
    """
    if not samples_ms:
        return {
            "count": 0,
            "min": None,
            "median": None,
            "p95": None,
            "max": None,
            "timeouts": int(timeouts),
        }

    sorted_samples = sorted(float(x) for x in samples_ms)
    n = len(sorted_samples)
    min_val = sorted_samples[0]
    max_val = sorted_samples[-1]

    # Median
    if n % 2 == 1:
        median_val = sorted_samples[n // 2]
    else:
        median_val = (
            sorted_samples[n // 2 - 1] + sorted_samples[n // 2]
        ) / 2.0

    # 95th percentile (linear interpolation between data points)
    if n == 1:
        p95_val = sorted_samples[0]
    else:
        rank = (n - 1) * 0.95
        lower = int(math.floor(rank))
        upper = int(math.ceil(rank))
        if lower == upper:
            p95_val = sorted_samples[lower]
        else:
            fraction = rank - lower
            p95_val = sorted_samples[lower] + fraction * (
                sorted_samples[upper] - sorted_samples[lower]
            )

    return {
        "count": n,
        "min": min_val,
        "median": median_val,
        "p95": p95_val,
        "max": max_val,
        "timeouts": int(timeouts),
    }


# ---------------------------------------------------------------------------
# Log line builder
# ---------------------------------------------------------------------------


def log_level_for_decision(decision: str) -> str:
    """Return the log level for a decision (Requirement 13.1).

    Args:
        decision: One of ``applied``, ``skipped``, ``conflict``, ``failed``.

    Returns:
        Log level string: ``INFO``, ``WARNING`` or ``ERROR``.
    """
    return DECISION_LOG_LEVELS.get(decision.strip().lower(), "INFO")


def build_log_line(
    decision: str, details: Dict[str, Any]
) -> Tuple[str, str]:
    """Build the single log entry for a job attempt (Requirement 13.1).

    The log line contains the decision, project name, AYON entity id, Kitsu
    id (or ``none``), Sync_Category and job id.

    Args:
        decision: One of ``applied``, ``skipped``, ``conflict``, ``failed``.
        details: Attempt details.

    Returns:
        A tuple of ``(level, message)``.
    """
    dec = decision.strip().lower()
    level = log_level_for_decision(dec)

    project = (
        details.get("project_name")
        or details.get("project")
        or NONE_VALUE
    )
    entity_id = (
        details.get("entity_id")
        or details.get("ayon_entity_id")
        or NONE_VALUE
    )
    kitsu_id = details.get("kitsu_id") or NONE_VALUE
    category = (
        details.get("category")
        or details.get("sync_category")
        or NONE_VALUE
    )
    job_id = (
        details.get("job_id")
        or details.get("outbound_job_id")
        or NONE_VALUE
    )

    msg = (
        f"Outbound job {job_id} [{dec}]: project={project}, "
        f"entity={entity_id}, kitsu_id={kitsu_id}, category={category}"
    )

    extra = details.get("message") or details.get("reason")
    if extra:
        msg = f"{msg} - {extra}"

    secrets = details.get("secrets")
    if secrets:
        msg = redact(msg, secrets)

    return level, msg


def log_line(decision: str, details: Dict[str, Any]) -> Tuple[str, str]:
    """Alias for ``build_log_line``."""
    return build_log_line(decision, details)


# ---------------------------------------------------------------------------
# Job descriptions
# ---------------------------------------------------------------------------


def _safe_int(val: Any, default: int = 1) -> int:
    """Safely convert a value to int with a fallback default."""
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _person_display_name(p: Any) -> str:
    """Format Zou person display name sorted by name (Requirement 7.4)."""
    if isinstance(p, dict):
        if p.get("name"):
            return str(p["name"])
        first = str(p.get("first_name", "")).strip()
        last = str(p.get("last_name", "")).strip()
        full = f"{first} {last}".strip()
        if full:
            return full
        return str(p.get("id") or p)
    return str(p)


def _format_value(field: str, val: Any) -> str:
    """Format a before, sent, or unwritten value cleanly."""
    if val is None or val == "" or val == NONE_VALUE:
        return NONE_VALUE

    # Assignees or lists/sets of values
    if field in UNORDERED_FIELDS or isinstance(
        val, (list, tuple, set, frozenset)
    ):
        items = list(val)
        if not items:
            return NONE_VALUE
        if isinstance(items[0], dict):
            # Sort assignees by Kitsu person name
            sorted_items = sorted(items, key=_person_display_name)
            names = [_person_display_name(p) for p in sorted_items]
            return f"[{', '.join(names)}]"
        names = sorted(str(x) for x in items)
        return f"[{', '.join(names)}]"

    return str(val)


def _format_write_record(w: Dict[str, Any]) -> str:
    """Format a single write record for job description (Req 7.4, 8.5)."""
    if not isinstance(w, dict):
        return str(w)
    action = w.get("action")
    if action in ("assign", "unassign"):
        name = w.get("person_name") or w.get("person_id") or w.get("sent")
        if w.get("before") is not None or w.get("sent") is not None:
            b_str = _format_value("assignees", w.get("before"))
            s_str = _format_value("assignees", w.get("sent"))
            return f"{action}ed {name} (before: {b_str}, sent: {s_str})"
        return f"{action}ed {name}"
    wf = w.get("field", "field")
    before = w.get("before") if "before" in w else w.get("old")
    sent = w.get("sent") if "sent" in w else w.get("new")
    if before is not None or sent is not None:
        b_str = _format_value(wf, before)
        s_str = _format_value(wf, sent)
        return f"field '{wf}' (before: {b_str}, sent: {s_str})"
    ws = _format_value(wf, sent)
    return f"field '{wf}' written as {ws}"


def _ensure_no_write_clause(text: str) -> str:
    """Ensure the 'no Kitsu field was written' clause is present."""
    if NO_KITSU_FIELD_WRITTEN in text.lower():
        return text
    clean = text.rstrip(". ")
    if not clean:
        return "No Kitsu field was written."
    return f"{clean}. No Kitsu field was written."


def describe_job(decision: str, details: Dict[str, Any]) -> str:
    """Format the Outbound_Job description (Requirements 4.3, 4.4, 13.2, 13.3).

    Args:
        decision: One of ``applied``, ``skipped``, ``conflict``, ``failed``.
        details: Details dict containing write info, skip reason or failure
            details.

    Returns:
        The formatted description string, prefixed with ``Applied:``,
        ``Skipped:``, ``Conflict:`` or ``Failed:``.
    """
    dec = decision.strip().lower()

    if dec == DECISION_APPLIED:
        desc = _describe_applied(details)
    elif dec == DECISION_SKIPPED:
        desc = _describe_skipped(details)
    elif dec == DECISION_CONFLICT:
        desc = _describe_conflict(details)
    elif dec == DECISION_FAILED:
        desc = _describe_failed(details)
    else:
        # Fallback for unrecognized decisions
        desc = f"{decision.capitalize()}: {details.get('message', '')}"

    secrets = details.get("secrets")
    if secrets:
        desc = redact(desc, secrets)
    return desc


def _describe_applied(details: Dict[str, Any]) -> str:
    """Format an applied Outbound_Job description."""
    parts: List[str] = []

    entity_type = (
        details.get("kitsu_entity_type")
        or details.get("entity_type")
        or ""
    )
    kitsu_id = details.get("kitsu_id") or ""
    header = ""
    if entity_type and kitsu_id:
        header = f"{entity_type} {kitsu_id}"
    elif kitsu_id:
        header = f"entity {kitsu_id}"

    # Extract written fields
    writes_parts: List[str] = []
    raw_writes = details.get("writes")
    if isinstance(raw_writes, list):
        for w in raw_writes:
            if isinstance(w, dict):
                fld = w.get("field", "field")
                before = w.get("before") if "before" in w else w.get("old")
                sent = w.get("sent") if "sent" in w else w.get("new")
                writes_parts.append(
                    f"{fld} (before: {_format_value(fld, before)}, "
                    f"sent: {_format_value(fld, sent)})"
                )
    elif isinstance(raw_writes, dict):
        for fld, w in raw_writes.items():
            if isinstance(w, dict):
                before = w.get("before") if "before" in w else w.get("old")
                sent = w.get("sent") if "sent" in w else w.get("new")
            else:
                before = None
                sent = w
            writes_parts.append(
                f"{fld} (before: {_format_value(fld, before)}, "
                f"sent: {_format_value(fld, sent)})"
            )
    elif details.get("field"):
        fld = str(details["field"])
        before = (
            details.get("before")
            if "before" in details
            else details.get("old")
        )
        sent = (
            details.get("sent")
            if "sent" in details
            else details.get("new")
        )
        writes_parts.append(
            f"{fld} (before: {_format_value(fld, before)}, "
            f"sent: {_format_value(fld, sent)})"
        )
    elif details.get("written_fields"):
        for fld in details["written_fields"]:
            writes_parts.append(f"{fld} written")

    if header and writes_parts:
        parts.append(f"{header} wrote {', '.join(writes_parts)}")
    elif header:
        parts.append(header)
    elif writes_parts:
        parts.append(f"wrote {', '.join(writes_parts)}")

    # Slice 3 rename details (12.1)
    if "previous_name" in details or "new_name" in details:
        p_name = details.get("previous_name", NONE_VALUE)
        n_name = details.get("new_name", NONE_VALUE)
        parts.append(f"name changed from '{p_name}' to '{n_name}'")

    # Slice 3 delete details (12.4)
    if details.get("deleted"):
        del_parts = []
        if kitsu_id:
            del_parts.append(f"kitsu_id={kitsu_id}")
        if details.get("kitsu_name"):
            del_parts.append(f"name='{details['kitsu_name']}'")
        if entity_type:
            del_parts.append(f"type={entity_type}")
        if details.get("ayon_entity_id"):
            del_parts.append(f"ayon_id={details['ayon_entity_id']}")
        parts.append(f"deleted ({', '.join(del_parts)})")

    # Additional notes
    if details.get("no_previous_value"):
        npv = details["no_previous_value"]
        if isinstance(npv, (list, tuple)):
            npv_str = ", ".join(npv)
        else:
            npv_str = str(npv)
        parts.append(f"no previous value for {npv_str}")

    if details.get("no_user") or details.get("missing_user"):
        parts.append("no known user in AYON event")

    if details.get("unresolved_assignees"):
        unres = ", ".join(str(u) for u in details["unresolved_assignees"])
        parts.append(f"unresolved assignees: {unres}")

    if details.get("added_assignees"):
        added = _format_value("assignees", details["added_assignees"])
        parts.append(f"added assignees: {added}")

    if details.get("removed_assignees"):
        removed = _format_value("assignees", details["removed_assignees"])
        parts.append(f"removed assignees: {removed}")

    skipped = (
        details.get("skipped_attributes") or details.get("skipped_fields")
    )
    if skipped:
        skp_str = ", ".join(str(s) for s in skipped)
        parts.append(f"skipped attributes: {skp_str}")

    inherited = (
        details.get("inherited_fields") or details.get("inherited_attributes")
    )
    if inherited:
        inh_str = ", ".join(str(s) for s in inherited)
        parts.append(f"skipped because inherited: {inh_str}")

    if details.get("message"):
        parts.append(str(details["message"]))

    content = "; ".join(parts) if parts else "change applied"
    if content.startswith(DESCRIPTION_APPLIED):
        return content
    return f"{DESCRIPTION_APPLIED} {content}"


def _describe_skipped(details: Dict[str, Any]) -> str:
    """Format a skipped Outbound_Job description."""
    raw_reason = (
        details.get("reason")
        or details.get("skip_reason")
        or details.get("message")
        or "skipped"
    )
    reason = str(raw_reason).strip()
    if reason.startswith(DESCRIPTION_SKIPPED):
        reason = reason[len(DESCRIPTION_SKIPPED):].strip()

    fld = details.get("field") or details.get("field_name")
    if reason.lower() == "already in sync" and fld:
        reason = f"{fld} already in sync"

    # Check for gated skip (Requirements 2.11, 4.3; Property 25)
    lower_reason = reason.lower()
    is_gated = (
        details.get("gated") is True
        or "disabled at event creation time" in lower_reason
        or "disabled for project" in lower_reason
        or "disabled now" in lower_reason
        or "toggle state was unknown" in lower_reason
        or "unknown toggle" in lower_reason
        or "invalid settings for project" in lower_reason
        or "no recorded toggle state" in lower_reason
    )

    if is_gated:
        event_id = (
            details.get("event_id")
            or details.get("source_event_id")
            or NONE_VALUE
        )
        project = (
            details.get("project_name")
            or details.get("project")
            or NONE_VALUE
        )
        category = (
            details.get("category")
            or details.get("sync_category")
            or NONE_VALUE
        )
        gated_tag = (
            f"[event={event_id}, project={project}, category={category}]"
        )
        if gated_tag not in reason:
            reason = f"{reason} {gated_tag}"

    if details.get("writes"):
        w_parts = [_format_write_record(w) for w in details["writes"]]
        body = f"{reason}. Written fields: {', '.join(w_parts)}"
    else:
        body = _ensure_no_write_clause(reason)
    return f"{DESCRIPTION_SKIPPED} {body}"


def _describe_conflict(details: Dict[str, Any]) -> str:
    """Format a conflict Outbound_Job description."""
    policy = (
        details.get("policy")
        or details.get("conflict_policy")
        or CONFLICT_POLICY_KITSU_WINS
    )

    conflicts = details.get("conflicts")
    if isinstance(conflicts, list) and conflicts:
        conflict_items = conflicts
    else:
        conflict_items = [details]

    parts: List[str] = []
    for item in conflict_items:
        fld = item.get("field") or item.get("field_name") or "field"
        prev = _format_value(
            fld,
            item.get("previous")
            if "previous" in item
            else item.get("old_value"),
        )
        current = _format_value(
            fld,
            item.get("kitsu_current")
            if "kitsu_current" in item
            else (
                item.get("current")
                if "current" in item
                else (
                    item.get("kitsu_value")
                    if "kitsu_value" in item
                    else item.get("overwritten")
                )
            ),
        )
        new_val = _format_value(
            fld,
            item.get("new")
            if "new" in item
            else (
                item.get("new_value")
                if "new_value" in item
                else (
                    item.get("rejected")
                    if "rejected" in item
                    else item.get("written")
                )
            ),
        )

        if policy == CONFLICT_POLICY_AYON_WINS:
            parts.append(
                f"field '{fld}' overwritten (overwritten Kitsu: {current}, "
                f"written AYON: {new_val})"
            )
        else:
            parts.append(
                f"field '{fld}' (previous AYON: {prev}, "
                f"current Kitsu: {current}, rejected AYON: {new_val})"
            )

    body = (
        "; ".join(parts)
        if parts
        else details.get("reason", "conflict detected")
    )
    if body.startswith(DESCRIPTION_CONFLICT):
        body = body[len(DESCRIPTION_CONFLICT):].strip()

    if details.get("writes"):
        w_parts = [_format_write_record(w) for w in details["writes"]]
        body = f"{body}; {', '.join(w_parts)}"

    if details.get("unresolved_assignees"):
        unres = ", ".join(str(u) for u in details["unresolved_assignees"])
        body = f"{body}; unresolved assignees: {unres}"

    if details.get("added_assignees"):
        added = _format_value("assignees", details["added_assignees"])
        body = f"{body}; added assignees: {added}"

    if details.get("removed_assignees"):
        removed = _format_value("assignees", details["removed_assignees"])
        body = f"{body}; removed assignees: {removed}"

    if details.get("no_previous_value"):
        npv = details["no_previous_value"]
        if isinstance(npv, (list, tuple)):
            npv_str = ", ".join(str(x) for x in npv)
        else:
            npv_str = str(npv)
        body = f"{body}; no previous value for {npv_str}"

    if policy == CONFLICT_POLICY_KITSU_WINS and not details.get("writes"):
        body = _ensure_no_write_clause(body)

    return f"{DESCRIPTION_CONFLICT} {body}"


def _describe_failed(details: Dict[str, Any]) -> str:
    """Format a failed Outbound_Job description."""
    is_retryable = bool(
        details.get("retryable") or details.get("is_retryable")
    )
    attempt = _safe_int(details.get("attempt"), 1)

    # Error text components
    error_kind = str(details.get("error_kind", ""))
    http_status = details.get("http_status") or details.get("status_code")
    err_str = str(details.get("error") or details.get("message") or "")

    if is_retryable:
        max_attempts = _safe_int(details.get("max_attempts"), MAX_ATTEMPTS)
        attempt_str = f"attempt {attempt}/{max_attempts}"

        is_unreach = (
            error_kind == "unreachable"
            or "unreachable" in err_str.lower()
            or bool(details.get("unreachable"))
        )
        if is_unreach:
            err_text = "Kitsu unreachable"
        elif http_status:
            err_text = f"Kitsu HTTP {http_status}"
        elif error_kind == "server_error":
            err_text = (
                f"Kitsu HTTP error ({err_str})"
                if err_str
                else "Kitsu HTTP error (status unknown)"
            )
        else:
            err_text = err_str or "Kitsu unreachable"

        reason = details.get("reason")
        if reason:
            body = f"{reason}: {attempt_str}, {err_text}"
        else:
            body = f"{attempt_str}, {err_text}"
    else:
        # Final failure (Requirement 10.6)
        entity_id = (
            details.get("entity_id")
            or details.get("ayon_entity_id")
            or NONE_VALUE
        )
        kitsu_id = details.get("kitsu_id") or NONE_VALUE
        category = (
            details.get("category")
            or details.get("sync_category")
            or NONE_VALUE
        )

        unwritten = (
            details.get("unwritten")
            if "unwritten" in details
            else (
                details.get("unwritten_values")
                if "unwritten_values" in details
                else details.get("unwritten_fields")
            )
        )
        if isinstance(unwritten, dict):
            unwritten_str = ", ".join(
                f"{k}={_format_value(k, v)}" for k, v in unwritten.items()
            )
        elif isinstance(unwritten, (list, tuple)):
            unwritten_str = ", ".join(str(x) for x in unwritten)
        elif unwritten:
            unwritten_str = str(unwritten)
        else:
            unwritten_str = NONE_VALUE

        reason = (
            details.get("reason")
            or details.get("message")
            or details.get("error")
            or ""
        )
        reason_str = str(reason).strip()
        if reason_str.startswith(DESCRIPTION_FAILED):
            reason_str = reason_str[len(DESCRIPTION_FAILED):].strip()

        body_parts = [
            f"entity {entity_id}",
            f"kitsu_id {kitsu_id}",
            f"category {category}",
            f"unwritten values: {unwritten_str}",
        ]
        if reason_str:
            body_parts.append(reason_str)
        body = ", ".join(body_parts)

    if details.get("writes"):
        w_parts = [_format_write_record(w) for w in details["writes"]]
        body = f"{body}. Written fields: {', '.join(w_parts)}"
    else:
        body = _ensure_no_write_clause(body)
    return f"{DESCRIPTION_FAILED} {body}"

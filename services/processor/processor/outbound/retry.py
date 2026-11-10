"""Retry policy of Outbound_Jobs (Requirement 10).

This module is part of the pure core: it imports only the standard
library, takes and returns built-in values, reads no clock and performs
no I/O (Requirement 14.1). Times are passed in by the runner.

* ``retry_decision`` tells whether a failed attempt is final. A
  Retryable_Kitsu_Failure (``unreachable``, ``server_error``) and an
  attempt interrupted by a Processor stop (``interrupted``) are retried
  until the 4th attempt. Every other error kind is final at once
  (Requirements 10.2, 10.3, 10.4, 10.6, 10.9).
* ``retry_due`` tells whether a held job may start its next attempt
  (10 s after the failure) and whether it is late (more than 60 s after
  the failure), not counting excluded time (Requirement 10.2).
* ``supersede_fields`` drops retried fields that a newer applied job has
  already written (Requirement 10.7).

The attempt count lives in ``summary.attempt``, not in the enroll
``retries`` counter, because enroll only excludes a failed job when
``retries > max_retries`` and would allow one attempt too many (F17).
On a final failure the runner sets ``retries`` to ``MAX_RETRIES + 1`` so
enroll never restarts the job.
"""

from .constants import (
    FINAL_KINDS,
    MAX_ATTEMPTS,
    MAX_RETRIES,
    RETRY_DEADLINE_S,
    RETRY_DELAY_S,
    RETRYABLE_KINDS,
    SKIP_SUPERSEDED,
)

# ---------------------------------------------------------------------------
# Error kinds (design "Data Models", "Error kinds")
# ---------------------------------------------------------------------------
#
# Defined in ``constants`` (shared with ``describe`` and ``kitsu_writer``)
# and re-exported here. Any kind not in ``RETRYABLE_KINDS`` is final,
# including unknown kinds; ``FINAL_KINDS`` only documents the known ones.

#: Value written to the job ``retries`` on a final failure, one above the
#: enroll ``max_retries``, so enroll never restarts the job (F17, 10.6).
FINAL_RETRIES_VALUE = MAX_RETRIES + 1

__all__ = [
    "FINAL_KINDS",
    "FINAL_RETRIES_VALUE",
    "RETRYABLE_KINDS",
    "retry_decision",
    "retry_due",
    "supersede_fields",
]


def _is_int(value):
    """Tell whether ``value`` is an ``int`` and not a ``bool``.

    Args:
        value: Any value.

    Returns:
        bool: ``True`` for a real integer.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    """Tell whether ``value`` is an ``int`` or ``float`` and not a ``bool``.

    Args:
        value: Any value.

    Returns:
        bool: ``True`` for a real number that is not NaN.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    # NaN is the only value that differs from itself.
    return value == value


def retry_decision(
    error_kind: str, attempt: int, max_attempts: int = MAX_ATTEMPTS
) -> dict:
    """Decide whether a failed attempt of an Outbound_Job is final.

    A retryable kind (``unreachable``, ``server_error``, ``interrupted``)
    is final only on the last allowed attempt (Requirements 10.2, 10.9).
    Every other kind, including an unknown or non-string kind, is final on
    any attempt (Requirements 10.3, 10.4, 10.6).

    Args:
        error_kind: Error kind of the failed attempt, one of the kinds in
            the design "Error kinds" list.
        attempt: Number of the attempt that failed, from 1, as stored in
            ``summary.attempt`` and carried across Processor restarts. A
            value below 1 counts as 1. A non-integer value counts as the
            last allowed attempt, so a broken counter never causes more
            attempts than allowed.
        max_attempts: Attempts allowed per Outbound_Job, 4 by default
            (``constants.MAX_ATTEMPTS``).

    Returns:
        dict: ``{"final": bool, "retries_value": int | None,
        "not_before_s": int | None, "not_after_s": int | None}``. When
        ``final`` is ``True``, ``retries_value`` is ``MAX_RETRIES + 1``
        (so enroll never restarts the job, F17) and both delays are
        ``None``. Otherwise ``retries_value`` is ``None`` (enroll
        increments the counter itself on restart) and the next attempt
        must start from ``not_before_s`` (10) to ``not_after_s`` (60)
        seconds after the failure (Requirement 10.2).
    """
    if not _is_int(max_attempts) or max_attempts < 1:
        max_attempts = MAX_ATTEMPTS
    if not _is_int(attempt):
        attempt = max_attempts
    attempt = max(attempt, 1)

    retryable = isinstance(error_kind, str) and error_kind in RETRYABLE_KINDS
    final = not retryable or attempt >= max_attempts

    if final:
        return {
            "final": True,
            "retries_value": FINAL_RETRIES_VALUE,
            "not_before_s": None,
            "not_after_s": None,
        }
    return {
        "final": False,
        "retries_value": None,
        "not_before_s": RETRY_DELAY_S,
        "not_after_s": RETRY_DEADLINE_S,
    }


def retry_due(last_failed_at: float, now: float, excluded_s: float) -> dict:
    """Tell whether a held Outbound_Job may start its next attempt.

    The elapsed time is ``now - last_failed_at - excluded_s``. The
    excluded time (time the Processor was stopped and time spent
    processing ``kitsu.sync_request`` jobs while the hold is active) is
    left out of both bounds. Leaving it out of the 10 s bound can only
    make the retry start later in wall-clock time, so the retry never
    starts earlier than 10 s after the failure under either reading of
    Requirement 10.2.

    Args:
        last_failed_at: Time of the failed attempt, in seconds (for
            example a POSIX timestamp).
        now: Current time on the same clock, in seconds.
        excluded_s: Seconds to leave out of the elapsed time. A negative
            or non-numeric value counts as 0.

    Returns:
        dict: ``{"due": bool, "late": bool}``. ``due`` is ``True`` from
        ``RETRY_DELAY_S`` (10 s) of elapsed time. ``late`` is ``True``
        once the elapsed time exceeds ``RETRY_DEADLINE_S`` (60 s); a late
        job is always due. When either time is not a number, the result
        is due and not late, so a broken timestamp never holds the global
        queue.
    """
    if not _is_number(last_failed_at) or not _is_number(now):
        return {"due": True, "late": False}
    if not _is_number(excluded_s) or excluded_s < 0:
        excluded_s = 0

    elapsed = now - last_failed_at - excluded_s
    return {
        "due": elapsed >= RETRY_DELAY_S,
        "late": elapsed > RETRY_DEADLINE_S,
    }


def _written_fields(job):
    """Collect the Kitsu field names a newer applied job wrote.

    Args:
        job: Newer job dict. Its fields are read from ``fields`` (a list
            of names) and from ``writes`` (the ``summary.writes`` shape,
            a list of ``{"field": name, ...}`` dicts).

    Returns:
        set[str]: Written field names; non-string entries are ignored.
    """
    fields = set()
    names = job.get("fields")
    if isinstance(names, (list, tuple, set, frozenset)):
        fields.update(name for name in names if isinstance(name, str))
    writes = job.get("writes")
    if isinstance(writes, (list, tuple)):
        for write in writes:
            if isinstance(write, dict) and isinstance(write.get("field"), str):
                fields.add(write["field"])
    summary = job.get("summary")
    if isinstance(summary, dict):
        s_names = summary.get("fields")
        if isinstance(s_names, (list, tuple, set, frozenset)):
            fields.update(name for name in s_names if isinstance(name, str))
        s_writes = summary.get("writes")
        if isinstance(s_writes, (list, tuple)):
            for write in s_writes:
                if (
                    isinstance(write, dict)
                    and isinstance(write.get("field"), str)
                ):
                    fields.add(write["field"])
    return fields


def _job_id(job):
    """Read the id of a newer job.

    Args:
        job: Newer job dict with ``jobId`` or ``id``.

    Returns:
        str | None: The first non-empty string id, else ``None``.
    """
    for key in ("jobId", "id"):
        value = job.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def supersede_fields(
    retried_fields: list[str], newer_writes: list[dict]
) -> dict:
    """Split the fields of a retry into omitted and kept fields.

    This is the safety net of Requirement 10.7. Under the global queue of
    Requirement 4.14, a job that failed with retries remaining defers every
    job with a newer source event, so a newer job normally cannot write
    to Kitsu before this retry starts, and the runner is not expected to
    find any superseded field in live runs (design gap 3). The runner
    still calls this function before every retry (``attempt > 1``), so a
    queue bypass (for example a reaped job or a manual restart) never
    overwrites a newer value with an older one.

    Args:
        retried_fields: Kitsu field names the retried job would write.
            Non-string entries are ignored; duplicates count once.
        newer_writes: Applied Outbound_Jobs of the same AYON entity and
            Sync_Category whose source event is newer than the retried
            job's source event. The caller does that filtering. Each item
            is ``{"jobId": str, "fields": [str]}`` or ``{"jobId": str,
            "writes": [{"field": str, ...}]}`` (``id`` is accepted in
            place of ``jobId``). Non-dict items are ignored.

    Returns:
        dict: ``{"omit": sorted fields, "keep": sorted fields,
        "newer_job_ids": sorted ids, "skip_reason": str | None}``.
        ``omit`` holds each retried field written by a newer job, ``keep``
        every other retried field, and ``newer_job_ids`` the ids of the
        newer jobs that wrote an omitted field. When ``keep`` is empty
        and at least one field was omitted, ``skip_reason`` is the
        ``SKIP_SUPERSEDED`` reason naming the newer job ids, and the
        runner finishes the job as ``Skipped:`` (Requirement 4.4);
        otherwise it is ``None``.
    """
    retried = set()
    if retried_fields is not None:
        try:
            r_list = list(retried_fields)
        except TypeError:
            r_list = []
        retried = {name for name in r_list if isinstance(name, str)}

    omit = set()
    newer_job_ids = set()
    if newer_writes is not None:
        try:
            entries = list(newer_writes)
        except TypeError:
            entries = []
        for job in entries:
            if not isinstance(job, dict):
                continue
            overlap = retried & _written_fields(job)
            if not overlap:
                continue
            omit |= overlap
            job_id = _job_id(job)
            if job_id is not None:
                newer_job_ids.add(job_id)

    keep = retried - omit
    job_ids = sorted(newer_job_ids)
    skip_reason = None
    if omit and not keep:
        skip_reason = SKIP_SUPERSEDED.format(job_ids=", ".join(job_ids))

    return {
        "omit": sorted(omit),
        "keep": sorted(keep),
        "newer_job_ids": job_ids,
        "skip_reason": skip_reason,
    }

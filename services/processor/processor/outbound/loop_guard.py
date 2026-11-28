"""Loop guard of the Outbound_Sync path (Requirement 5.9).

This module is part of the pure core: it imports only the standard library,
performs no I/O and never reads a clock (Requirement 14.1). The caller
passes the current time in seconds.

The loop guard is the third line of defence against echo loops, after the
origin classification and the value comparison. It keeps an in-memory
sliding window per ``(AYON entity id, field)``:

* A write attempt inside an open suppression is refused. The handler
  finishes the Outbound_Job as ``skipped`` with ``Skipped: loop
  suspected``, sends no Kitsu request and never retries the job.
* Otherwise the write is allowed and recorded. When it is the 3rd allowed
  write within 60 s, it opens a 300 s suppression that starts at the time
  of that write.

A refused attempt is not recorded, so suppressed attempts cannot extend
the suppression. The window is inclusive: two writes exactly 60 s apart
count as being within the same 60-second interval, which is the stricter
reading of Requirement 5.9.

The guard state is a plain dict and is not persisted, so a restart resets
it (design, "Loop guard state"):

``{(entity_id, field): {"write_times": [float], "suppressed_until":
float | None}}``

Every function returns new values and never mutates its input. Entries
with no write inside the window and no open suppression are pruned, so the
state stays bounded by the number of keys written in the last
``LOOP_GUARD_SUPPRESS_S`` seconds.
"""

from .constants import (
    DECISION_SKIPPED,
    LOOP_GUARD_MAX_WRITES,
    LOOP_GUARD_SUPPRESS_S,
    LOOP_GUARD_WINDOW_S,
    SKIP_LOOP_SUSPECTED,
)


def _is_suppressed(suppressed_until: float | None, now: float) -> bool:
    """Tell whether a suppression is still open at ``now``.

    The suppression covers the 300 seconds after the 3rd write, so it ends
    at ``suppressed_until`` itself.

    Args:
        suppressed_until: End of the suppression, or ``None``.
        now: Current time in seconds.

    Returns:
        ``True`` while ``now`` is before ``suppressed_until``.
    """
    return suppressed_until is not None and now < suppressed_until


def _recent_writes(write_times: list[float], now: float) -> list[float]:
    """Return the write times that are inside the window ending at ``now``.

    Args:
        write_times: Recorded write times in seconds, in any order.
        now: Current time in seconds.

    Returns:
        A new sorted list of the times not older than
        ``LOOP_GUARD_WINDOW_S`` seconds.
    """
    window_start = now - LOOP_GUARD_WINDOW_S
    return sorted(t for t in write_times if t >= window_start)


def loop_guard_check(
    write_times: list[float],
    suppressed_until: float | None,
    now: float,
) -> dict:
    """Decide whether one Kitsu write of one field may be sent.

    Args:
        write_times: Times in seconds of the allowed writes recorded for
            the ``(entity, field)`` key. Not mutated.
        suppressed_until: End of the open suppression in seconds, or
            ``None``.
        now: Current time in seconds.

    Returns:
        ``{"allowed": bool, "write_times": [...], "suppressed_until":
        float | None, "decision": str | None, "reason": str | None}``.
        ``write_times`` and ``suppressed_until`` are the new state of the
        key, with write times outside the window dropped and an expired
        suppression cleared. A refused write has the decision ``skipped``
        and the reason ``loop suspected``; the job is finished, never
        failed. An allowed write has ``None`` for both.
    """
    recent = _recent_writes(write_times, now)

    if _is_suppressed(suppressed_until, now):
        return {
            "allowed": False,
            "write_times": recent,
            "suppressed_until": suppressed_until,
            "decision": DECISION_SKIPPED,
            "reason": SKIP_LOOP_SUSPECTED,
        }

    recent.append(now)
    new_suppressed_until = None
    if len(recent) >= LOOP_GUARD_MAX_WRITES:
        new_suppressed_until = now + LOOP_GUARD_SUPPRESS_S
    return {
        "allowed": True,
        "write_times": recent,
        "suppressed_until": new_suppressed_until,
        "decision": None,
        "reason": None,
    }


def prune_loop_guard_state(state: dict, now: float) -> dict:
    """Drop the entries that no longer affect any decision.

    An entry is kept while it has a write inside the window or an open
    suppression. Kept entries get their expired write times dropped and an
    expired suppression cleared.

    Args:
        state: Guard state ``{(entity_id, field): {"write_times": [...],
            "suppressed_until": float | None}}``. Not mutated.
        now: Current time in seconds.

    Returns:
        A new guard state holding only the live entries.
    """
    pruned = {}
    for key, entry in state.items():
        recent = _recent_writes(entry.get("write_times") or [], now)
        suppressed_until = entry.get("suppressed_until")
        if not _is_suppressed(suppressed_until, now):
            suppressed_until = None
        if recent or suppressed_until is not None:
            pruned[key] = {
                "write_times": recent,
                "suppressed_until": suppressed_until,
            }
    return pruned


def loop_guard_apply(
    state: dict,
    entity_id: str,
    field: str,
    now: float,
) -> tuple[dict, dict]:
    """Run ``loop_guard_check`` for one key of the whole guard state.

    The state is pruned first (see ``prune_loop_guard_state``), so it
    cannot grow without bound.

    Args:
        state: Guard state ``{(entity_id, field): {"write_times": [...],
            "suppressed_until": float | None}}``. Not mutated.
        entity_id: AYON entity id of the Paired_Entity.
        field: Kitsu field name, for example ``task_status_id``.
        now: Current time in seconds.

    Returns:
        ``(result, new_state)``: ``result`` is the dict returned by
        ``loop_guard_check`` for the key, and ``new_state`` is the pruned
        guard state with the entry of the key updated.
    """
    key = (entity_id, field)
    new_state = prune_loop_guard_state(state, now)
    entry = new_state.get(key) or {}
    result = loop_guard_check(
        entry.get("write_times") or [],
        entry.get("suppressed_until"),
        now,
    )
    new_state[key] = {
        "write_times": list(result["write_times"]),
        "suppressed_until": result["suppressed_until"],
    }
    return result, new_state


__all__ = (
    "loop_guard_apply",
    "loop_guard_check",
    "prune_loop_guard_state",
)

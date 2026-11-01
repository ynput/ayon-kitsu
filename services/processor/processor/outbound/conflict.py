"""Per-field Conflict detection and job outcome of the Outbound_Sync path.

This module is part of the pure core: it imports only the standard library
and performs no I/O (Requirement 14.1).

``decide_field`` applies the field decision table of Requirement 9 to one
field whose values are already converted to Kitsu form:

1. The current Kitsu value equals the new value: ``skip_in_sync``. This
   check comes first, so the conflict policy is never applied to a field
   that is already in sync (Requirements 5.4, 9.7).
2. The event carries no previous value: ``write_no_previous``, without a
   Conflict comparison (Requirement 9.6).
3. The current Kitsu value equals the previous value: ``write``
   (Requirement 9.1).
4. Otherwise the field is in Conflict and the policy decides:
   ``conflict_keep_kitsu`` under ``kitsu_wins`` and ``conflict_overwrite``
   under ``ayon_wins`` (Requirements 9.2, 9.4, 9.5).

Set values (assignees) compare as unordered sets, so order and duplicates
do not matter (Requirements 5.4, 9.1).

``job_outcome`` combines the field decisions of one Outbound_Job into the
job decision.
"""

from typing import Any

from .constants import (
    CONFLICT_POLICY_AYON_WINS,
    DECISION_APPLIED,
    DECISION_CONFLICT,
    DECISION_FAILED,
    UNORDERED_FIELDS,
)

# ---------------------------------------------------------------------------
# Field actions returned by ``decide_field``
# ---------------------------------------------------------------------------

ACTION_SKIP_IN_SYNC = "skip_in_sync"
ACTION_WRITE = "write"
ACTION_WRITE_NO_PREVIOUS = "write_no_previous"
ACTION_CONFLICT_KEEP_KITSU = "conflict_keep_kitsu"
ACTION_CONFLICT_OVERWRITE = "conflict_overwrite"

FIELD_ACTIONS = (
    ACTION_SKIP_IN_SYNC,
    ACTION_WRITE,
    ACTION_WRITE_NO_PREVIOUS,
    ACTION_CONFLICT_KEEP_KITSU,
    ACTION_CONFLICT_OVERWRITE,
)

#: Actions after which the handler sends a Kitsu write for the field.
WRITE_ACTIONS = frozenset(
    (ACTION_WRITE, ACTION_WRITE_NO_PREVIOUS, ACTION_CONFLICT_OVERWRITE)
)

#: Actions that mark a Conflict (description starts with ``Conflict:``).
CONFLICT_ACTIONS = frozenset(
    (ACTION_CONFLICT_KEEP_KITSU, ACTION_CONFLICT_OVERWRITE)
)

# ---------------------------------------------------------------------------
# Job outcomes returned by ``job_outcome``
# ---------------------------------------------------------------------------

OUTCOME_APPLIED = DECISION_APPLIED
OUTCOME_CONFLICT = DECISION_CONFLICT
OUTCOME_FAILED = DECISION_FAILED
#: Every field already in sync. The runner finishes the job with the
#: decision ``skipped`` and ``Skipped: already in sync`` (Requirement 5.4).
OUTCOME_SKIPPED_IN_SYNC = "skipped_in_sync"

JOB_OUTCOMES = (
    OUTCOME_APPLIED,
    OUTCOME_SKIPPED_IN_SYNC,
    OUTCOME_CONFLICT,
    OUTCOME_FAILED,
)


def _normalize(field: str, value: Any) -> Any:
    """Return the comparable form of one Kitsu-form value.

    Sets become frozensets. Lists and tuples of an unordered field
    (assignees) also become frozensets, so order and duplicates are
    ignored. Other values are returned unchanged.

    Args:
        field: Kitsu field name.
        value: Value in Kitsu form.

    Returns:
        The value in a form suitable for ``==``.
    """
    if isinstance(value, (set, frozenset)):
        return frozenset(value)
    if field in UNORDERED_FIELDS and isinstance(value, (list, tuple)):
        return frozenset(value)
    return value


def values_equal(field: str, left: Any, right: Any) -> bool:
    """Compare two Kitsu-form values of one field.

    Sets compare unordered. When one side is a set and the other a list or
    tuple, the list is compared as a set too, so a set of assignees equals
    the same person ids given as a list in any order.

    Args:
        field: Kitsu field name.
        left: First value in Kitsu form.
        right: Second value in Kitsu form.

    Returns:
        ``True`` when both values are equal after normalization.
    """
    left_value = _normalize(field, left)
    right_value = _normalize(field, right)
    if isinstance(left_value, frozenset) and isinstance(
        right_value, (list, tuple)
    ):
        right_value = frozenset(right_value)
    elif isinstance(right_value, frozenset) and isinstance(
        left_value, (list, tuple)
    ):
        left_value = frozenset(left_value)
    try:
        return bool(left_value == right_value)
    except TypeError:
        # Unhashable members cannot be compared as sets; treat as different.
        return False


def decide_field(
    field: str,
    previous: Any,
    kitsu_current: Any,
    new: Any,
    has_previous: bool,
    policy: str,
) -> dict:
    """Decide what the handler does with one field of an Outbound_Job.

    Values are already converted to Kitsu form (sets for assignees). The
    in-sync check comes first, so the policy is never applied to a field
    whose Kitsu value already equals the new value (Requirement 9.7).

    Args:
        field: Kitsu field name, for example ``task_status_id``.
        previous: Previous AYON value in Kitsu form. Ignored when
            ``has_previous`` is ``False``.
        kitsu_current: Current Kitsu value read before the write.
        new: New AYON value in Kitsu form.
        has_previous: Whether the AYON_Change_Event carries a usable
            previous value for the field.
        policy: Conflict policy, ``kitsu_wins`` or ``ayon_wins``. Any other
            value is treated as ``kitsu_wins``, which leaves Kitsu
            unchanged.

    Returns:
        ``{"action": "skip_in_sync" | "write" | "write_no_previous" |
        "conflict_keep_kitsu" | "conflict_overwrite", "field": field}``.
    """
    if values_equal(field, kitsu_current, new):
        action = ACTION_SKIP_IN_SYNC
    elif not has_previous:
        action = ACTION_WRITE_NO_PREVIOUS
    elif values_equal(field, previous, kitsu_current):
        action = ACTION_WRITE
    elif policy == CONFLICT_POLICY_AYON_WINS:
        action = ACTION_CONFLICT_OVERWRITE
    else:
        # ``kitsu_wins`` and any unexpected value keep Kitsu unchanged.
        action = ACTION_CONFLICT_KEEP_KITSU
    return {"action": action, "field": field}


def job_outcome(field_decisions: list[dict], errors: list[str]) -> str:
    """Aggregate per-field decisions into the job decision.

    The rules are applied in order:

    1. Any error gives ``"failed"``. Fields written before the error stay
       written (for example an invalid frame range, Requirement 8.3).
    2. Every field ``skip_in_sync`` gives ``"skipped_in_sync"``
       (Requirement 5.4). An empty list of decisions also gives it, since
       no field needs a write.
    3. Any Conflict decision gives ``"conflict"`` (Requirements 9.4, 9.5).
       The other fields are still handled as without a Conflict (9.2).
    4. Otherwise ``"applied"``.

    Args:
        field_decisions: Results of ``decide_field``, one per field.
        errors: Error messages collected while handling the job.

    Returns:
        One of ``"applied"``, ``"skipped_in_sync"``, ``"conflict"`` or
        ``"failed"``.

    Raises:
        ValueError: If a decision carries an unknown action.
    """
    actions = [decision.get("action") for decision in field_decisions]
    for action in actions:
        if action not in FIELD_ACTIONS:
            raise ValueError(f"Unknown field action: {action!r}")

    if errors:
        return OUTCOME_FAILED
    if all(action == ACTION_SKIP_IN_SYNC for action in actions):
        return OUTCOME_SKIPPED_IN_SYNC
    if any(action in CONFLICT_ACTIONS for action in actions):
        return OUTCOME_CONFLICT
    return OUTCOME_APPLIED


__all__ = (
    "ACTION_CONFLICT_KEEP_KITSU",
    "ACTION_CONFLICT_OVERWRITE",
    "ACTION_SKIP_IN_SYNC",
    "ACTION_WRITE",
    "ACTION_WRITE_NO_PREVIOUS",
    "CONFLICT_ACTIONS",
    "FIELD_ACTIONS",
    "JOB_OUTCOMES",
    "OUTCOME_APPLIED",
    "OUTCOME_CONFLICT",
    "OUTCOME_FAILED",
    "OUTCOME_SKIPPED_IN_SYNC",
    "UNORDERED_FIELDS",
    "WRITE_ACTIONS",
    "decide_field",
    "job_outcome",
    "values_equal",
)

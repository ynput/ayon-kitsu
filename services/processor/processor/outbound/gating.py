"""Settings gating of the Outbound_Sync path (Requirements 2 and 4).

This module is part of the pure core: it imports only the standard
library, takes and returns built-in values, performs no I/O and reads no
clock (Requirement 14.1). Every time is passed in, either as an ISO 8601
string (``"2025-01-01T10:00:00Z"``; a time without an offset is read as
UTC) or as a number of seconds since the Unix epoch.

A write to Kitsu is allowed only when the master toggle and the toggle of
the change's Sync_Category are enabled both at the event creation time and
at processing time. Unknown state means disabled:

* ``resolve_effective_toggles`` merges studio and project settings key by
  key and fails closed on a missing or non-bool toggle (2.6, 2.10).
* ``find_unknown_gap`` computes the interval between the last observed
  toggle state and the Processor start, and marks it as an
  Unknown_Toggle_Gap when the kitsu addon settings changed inside it
  (4.7, 4.12).
* ``toggles_at`` tells which toggle state applies at an event creation
  time: a recorded snapshot, an unknown gap, or no recorded state at all.
* ``gate_decision`` turns the state at creation and the state now into an
  allow or a skip with its reason (2.3, 2.4, 2.8, 4.8, 4.12, design gap 1).
* ``categories_for`` lists the Sync_Categories an event carries (4.1).
"""

import json
import math
from datetime import datetime, timezone
from typing import Any, Optional

from .constants import (
    CONFLICT_POLICIES,
    CONFLICT_POLICY_KEY,
    DEFAULT_CONFLICT_POLICY,
    MASTER_TOGGLE_KEY,
    SKIP_CATEGORY_DISABLED,
    SKIP_DISABLED_AT_CREATION,
    SKIP_DISABLED_NO_HISTORY,
    SKIP_UNKNOWN_TOGGLE_STATE,
    SYNC_CATEGORIES,
    TOPIC_CATEGORIES,
)

#: Settings path of the Two_Way_Sync_Settings, used in error messages.
SETTINGS_PATH = "sync_settings.two_way_sync"

#: States returned by ``toggles_at``.
STATE_SNAPSHOT = "snapshot"
STATE_UNKNOWN_GAP = "unknown_gap"
STATE_NO_HISTORY = "no_history"

#: Toggle keys in settings order: the master toggle, then the categories.
_TOGGLE_KEYS = (MASTER_TOGGLE_KEY,) + tuple(SYNC_CATEGORIES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_seconds(value, name):
    """Convert a time to seconds since the Unix epoch.

    Args:
        value: ISO 8601 string (a trailing ``Z`` and a missing offset both
            mean UTC) or a finite ``int`` or ``float`` of epoch seconds.
        name: Name of the value, used in the error message.

    Returns:
        float: Seconds since the Unix epoch.

    Raises:
        ValueError: When ``value`` is not a readable time. A ``bool`` is
            rejected even though it is an ``int``.
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} is not a time: {value!r}")
    if isinstance(value, (int, float)):
        seconds = float(value)
        if not math.isfinite(seconds):
            raise ValueError(f"{name} is not a finite time: {value!r}")
        return seconds
    if isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(
                f"{name} is not an ISO 8601 time: {value!r}"
            ) from None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    raise ValueError(f"{name} is not a time: {value!r}")


def to_seconds_safe(value: Any) -> Optional[float]:
    """Convert an ISO string or number to epoch seconds, or None if invalid.

    Args:
        value: Any time representation.

    Returns:
        float | None: Epoch seconds or None.
    """
    if value is None:
        return None
    try:
        return _to_seconds(value, "time")
    except (ValueError, TypeError):
        return None


def _settings_section(settings, required):
    """Find the Two_Way_Sync_Settings section in a settings dict.

    Accepted shapes: the full addon settings (``{"sync_settings":
    {"two_way_sync": {...}}}``), the sync settings (``{"two_way_sync":
    {...}}``) or the section itself.

    Args:
        settings: Settings dict, or ``None`` when it could not be read.
        required: ``True`` for the studio settings, where a missing
            section is an error. ``False`` for a project override, where a
            missing section means no override.

    Returns:
        tuple[dict | None, str | None]: The section and ``None``, or
        ``None`` and an error naming the setting that could not be read.
    """
    if settings is None:
        if required:
            return None, f"{SETTINGS_PATH} could not be read"
        return {}, None
    if not isinstance(settings, dict):
        return None, f"{SETTINGS_PATH} could not be read (not a dict)"

    node = settings
    if "sync_settings" in node:
        node = node["sync_settings"]
        if not isinstance(node, dict):
            return None, "sync_settings is not a dict"
        if "two_way_sync" not in node:
            if required:
                return None, f"{SETTINGS_PATH} is missing"
            return {}, None
        node = node["two_way_sync"]
    elif "two_way_sync" in node:
        node = node["two_way_sync"]

    if not isinstance(node, dict):
        return None, f"{SETTINGS_PATH} is not a dict"
    return node, None


def _disabled_toggles(error, conflict_policy):
    """Build the fail-closed result of ``resolve_effective_toggles``.

    Args:
        error: Error naming the offending setting.
        conflict_policy: Conflict policy to report.

    Returns:
        dict: EffectiveToggles with ``valid=False`` and every toggle
        disabled.
    """
    return {
        "valid": False,
        "error": error,
        "master": False,
        "categories": {name: False for name in SYNC_CATEGORIES},
        "conflict_policy": conflict_policy,
    }


def _category_enabled(toggles, category):
    """Tell whether a valid toggle state enables a category.

    Args:
        toggles: EffectiveToggles dict, or any other value.
        category: Sync_Category name.

    Returns:
        bool: ``True`` only when ``toggles`` is a dict with ``valid``,
        ``master`` and ``categories[category]`` all exactly ``True``.
    """
    if not isinstance(toggles, dict):
        return False
    if toggles.get("valid") is not True or toggles.get("master") is not True:
        return False
    categories = toggles.get("categories")
    if not isinstance(categories, dict):
        return False
    return categories.get(category) is True


def _gap_of(entry):
    """Unwrap a gap marker.

    Args:
        entry: Either the dict returned by ``find_unknown_gap`` or a gap
            marker summary ``{"gap": {...}, ...}`` as persisted on the
            ``kitsu.outbound_gate`` event.

    Returns:
        dict | None: The gap dict, or ``None`` when ``entry`` is none.
    """
    if not isinstance(entry, dict):
        return None
    inner = entry.get("gap")
    if isinstance(inner, dict):
        return inner
    return entry


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def resolve_effective_toggles(
    studio: dict | None, project: dict | None
) -> dict:
    """Compute the effective Two_Way_Sync_Settings of one project.

    Project values override studio values key by key (Requirement 2.6). A
    project key counts as defined when it is present, whatever its value,
    so a project value of ``None`` is an invalid override, not a fallback.
    When a toggle value that takes effect is missing or not a ``bool``, or
    the studio settings could not be read, the result is invalid and every
    toggle is disabled (Requirement 2.10). The error names the first
    offending setting in settings order; the caller adds the project name
    when it logs it.

    The conflict policy follows the same precedence. A missing or unknown
    policy falls back to ``kitsu_wins``, the policy that never overwrites
    Kitsu, and does not make the result invalid.

    Args:
        studio: Studio addon settings (see ``_settings_section`` for the
            accepted shapes), or ``None`` when they could not be read.
        project: Project addon settings or partial project overrides in
            the same shapes, or ``None`` when the project has none.

    Returns:
        dict: ``{"valid": bool, "error": str | None, "master": bool,
        "categories": {name: bool}, "conflict_policy": str}`` with one
        entry in ``categories`` per Sync_Category.
    """
    studio_section, studio_error = _settings_section(studio, required=True)
    project_section, project_error = _settings_section(project, required=False)
    studio_section = studio_section or {}
    project_section = project_section or {}

    if CONFLICT_POLICY_KEY in project_section:
        policy = project_section[CONFLICT_POLICY_KEY]
    else:
        policy = studio_section.get(CONFLICT_POLICY_KEY)
    if not isinstance(policy, str) or policy not in CONFLICT_POLICIES:
        policy = DEFAULT_CONFLICT_POLICY

    error = studio_error or project_error
    if error is not None:
        return _disabled_toggles(error, policy)

    values = {}
    for key in _TOGGLE_KEYS:
        if key in project_section:
            value = project_section[key]
        elif key in studio_section:
            value = studio_section[key]
        else:
            return _disabled_toggles(
                f"{SETTINGS_PATH}.{key} is missing", policy
            )
        if not isinstance(value, bool):
            return _disabled_toggles(
                f"{SETTINGS_PATH}.{key} is not a bool", policy
            )
        values[key] = value

    return {
        "valid": True,
        "error": None,
        "master": values[MASTER_TOGGLE_KEY],
        "categories": {name: values[name] for name in SYNC_CATEGORIES},
        "conflict_policy": policy,
    }


def find_unknown_gap(
    last_observed_at: str | None,
    started_at: str,
    settings_changed_at: list[str],
) -> dict | None:
    """Compute the interval the Processor did not observe (4.7, 4.12).

    The interval runs from the last toggle state observed before the stop
    to the start, both ends included. It is an Unknown_Toggle_Gap when at
    least one ``settings.changed`` event of the kitsu addon was created
    inside it. When the start is before the last observation (clock skew),
    the interval is empty: ``durationS`` is ``0.0`` and no change counts.

    Args:
        last_observed_at: ``lastObservedAt`` of the latest gate event of
            any instance, or ``None`` when there is no previous run.
        started_at: Time the Processor started.
        settings_changed_at: Creation times of the ``settings.changed``
            events of the kitsu addon.

    Returns:
        dict | None: ``{"from": last_observed_at, "to": started_at,
        "unknown": bool, "durationS": float, "settingsChanges": int}``
        (``from`` and ``to`` are the values passed in), or ``None`` when
        there is no previous observation (empty interval, 4.7).

    Raises:
        ValueError: When a time cannot be read.
    """
    if last_observed_at is None:
        return None

    start = _to_seconds(last_observed_at, "last_observed_at")
    end = _to_seconds(started_at, "started_at")

    changes = 0
    for index, changed_at in enumerate(settings_changed_at or ()):
        moment = _to_seconds(changed_at, f"settings_changed_at[{index}]")
        if start <= moment <= end:
            changes += 1

    return {
        "from": last_observed_at,
        "to": started_at,
        "unknown": changes > 0,
        "durationS": max(0.0, end - start),
        "settingsChanges": changes,
    }


def toggles_at(history: list[dict], gaps: list[dict], created_at: str) -> dict:
    """Tell which toggle state applies at an event creation time.

    ``unknown_gap`` wins when ``created_at`` lies in a gap with
    ``unknown=True``, both ends included. Otherwise the latest snapshot
    with ``observedAt <= created_at`` applies; among snapshots with the
    same ``observedAt`` the last one in ``history`` wins. Without such a
    snapshot the state is ``no_history``.

    Args:
        history: Gate snapshots of one project, each a dict with
            ``observedAt`` and ``toggles`` (EffectiveToggles). Gap markers
            (dicts with a ``gap`` key) and non-dict entries are ignored.
        gaps: Gap markers, either as returned by ``find_unknown_gap`` or
            as persisted (``{"gap": {...}, ...}``). ``None`` entries are
            ignored.
        created_at: Creation time of the AYON_Change_Event.

    Returns:
        dict: ``{"state": "snapshot" | "unknown_gap" | "no_history",
        "toggles": dict | None}``. ``toggles`` is the snapshot's toggles
        for ``snapshot`` and ``None`` otherwise.

    Raises:
        ValueError: When ``created_at``, a gap bound or a snapshot
            ``observedAt`` cannot be read.
    """
    moment = _to_seconds(created_at, "created_at")

    for index, entry in enumerate(gaps or ()):
        gap = _gap_of(entry)
        if gap is None or gap.get("unknown") is not True:
            continue
        start = _to_seconds(gap.get("from"), f"gaps[{index}].from")
        end = _to_seconds(gap.get("to"), f"gaps[{index}].to")
        if start <= moment <= end:
            return {"state": STATE_UNKNOWN_GAP, "toggles": None}

    best = None
    best_at = None
    for index, snapshot in enumerate(history or ()):
        if not isinstance(snapshot, dict) or "gap" in snapshot:
            continue
        observed_at = _to_seconds(
            snapshot.get("observedAt"), f"history[{index}].observedAt"
        )
        if observed_at <= moment and (
            best_at is None or observed_at >= best_at
        ):
            best = snapshot
            best_at = observed_at

    if best is None:
        return {"state": STATE_NO_HISTORY, "toggles": None}
    return {"state": STATE_SNAPSHOT, "toggles": best.get("toggles")}


def gate_decision(category: str, at_creation: dict, now: dict) -> dict:
    """Decide whether a Sync_Category of an event may be written to Kitsu.

    The write is allowed only when the category is enabled both at the
    event creation time and now. The checks run in this order, and the
    first that applies gives the reason:

    1. ``at_creation`` is ``unknown_gap``: toggle state unknown while the
       Processor was stopped, whatever the current toggles are (4.12).
    2. ``at_creation`` is ``no_history``: disabled at creation time, with
       no recorded toggle state (design gap 1).
    3. The snapshot at creation is invalid or has the master toggle or the
       category disabled, or the state is not recognised: disabled at
       creation time (2.8, 4.8).
    4. ``now`` is invalid or has the master toggle or the category
       disabled: disabled now (2.3, 2.4, 2.10).

    Args:
        category: Sync_Category name.
        at_creation: Result of ``toggles_at`` for the event creation time.
        now: Current EffectiveToggles of the event's project, as returned
            by ``resolve_effective_toggles``.

    Returns:
        dict: ``{"allowed": bool, "reason": str | None}``. ``reason`` is
        ``None`` when allowed, otherwise a skip reason without the
        ``Skipped:`` prefix.
    """
    state = at_creation.get("state") if isinstance(at_creation, dict) else None

    if state == STATE_UNKNOWN_GAP:
        return {"allowed": False, "reason": SKIP_UNKNOWN_TOGGLE_STATE}
    if state == STATE_NO_HISTORY:
        return {
            "allowed": False,
            "reason": SKIP_DISABLED_NO_HISTORY.format(category=category),
        }
    if state != STATE_SNAPSHOT or not _category_enabled(
        at_creation.get("toggles"), category
    ):
        return {
            "allowed": False,
            "reason": SKIP_DISABLED_AT_CREATION.format(category=category),
        }
    if not _category_enabled(now, category):
        return {
            "allowed": False,
            "reason": SKIP_CATEGORY_DISABLED.format(category=category),
        }
    return {"allowed": True, "reason": None}


def categories_for(event: dict) -> list[str]:
    """List every Sync_Category an event carries (4.1).

    With the specific topics this is at most one. Project and user
    deletion (out of scope, 12.6) and unknown topics carry none.

    Args:
        event: Event dict with a ``topic`` key.

    Returns:
        list[str]: Sync_Category names, empty when out of scope.
    """
    if not isinstance(event, dict):
        return []
    topic = event.get("topic")
    if not isinstance(topic, str):
        return []
    category = TOPIC_CATEGORIES.get(topic)
    if category is None:
        return []
    return [category]


def ensure_dict(val: Any) -> dict[str, Any]:
    """Parse JSON string into dict or return dict if already a dict.

    Args:
        val: Input value (dict, JSON string, or None).

    Returns:
        Dict value, empty dict if parsing fails or input is None/invalid.
    """
    if isinstance(val, dict):
        return val
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}

"""Origin classification of AYON change events (Requirement 5).

This module is part of the pure core: it imports only the standard
library, takes and returns built-in values and performs no I/O
(Requirement 14.1).

An AYON_Change_Event is classified from the event alone, never from
timing or from comparing entity values (Requirements 5.6, 5.7):

* ``sync_originated``: the event carries an origin marker of Inbound_Sync
  or Full_Sync (the ``kitsu_sync`` sender type, a ``kitsu-processor-``
  sender or a true ``summary.kitsuSyncOrigin``). The runner skips it with
  ``sync originated`` (Requirements 5.1, 5.12).
* ``user_change``: no marker, but a non-empty user or sender (a person or
  another integration).
* ``origin_unknown``: no marker, no user and no sender. The runner skips
  it with ``origin unknown`` (Requirement 5.8).
"""

from .constants import (
    ENROLL_EXCLUSION_TOPICS,
    KITSU_SYNC_SENDER_PREFIX,
    KITSU_SYNC_SENDER_TYPE,
    KITSU_SYNC_SUMMARY_KEY,
    ORIGIN_SYNC_ORIGINATED,
    ORIGIN_UNKNOWN,
    ORIGIN_USER_CHANGE,
)

#: Event keys that may hold the sender type. ``GET /api/events`` and
#: enroll return ``senderType``; the database column is ``sender_type``.
_SENDER_TYPE_KEYS = ("senderType", "sender_type")


def _non_empty_str(value):
    """Return the stripped string, or ``None`` when it is not usable.

    Args:
        value: Any value read from the event.

    Returns:
        str | None: ``value`` without surrounding whitespace when it is a
        string with at least one non-whitespace character, else ``None``.
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _marker(markers, key, default):
    """Read one marker value, falling back to the default marker.

    Args:
        markers: Marker dict as in ``constants.ORIGIN_MARKERS``, or any
            other value.
        key: Marker key (``sender_type``, ``sender_prefix`` or
            ``summary_key``).
        default: Value used when ``markers`` has no usable string for
            ``key``.

    Returns:
        str: A non-empty marker string. An empty marker is never used,
        because an empty sender prefix would match every sender.
    """
    if isinstance(markers, dict):
        value = _non_empty_str(markers.get(key))
        if value is not None:
            return value
    return default


def _has_origin_marker(event, markers):
    """Tell whether the event carries any origin marker.

    Args:
        event: Event dict.
        markers: Marker dict as in ``constants.ORIGIN_MARKERS``.

    Returns:
        bool: ``True`` when the sender type equals the marker sender type,
        the sender starts with the marker prefix, or the summary marker
        key is ``True``.
    """
    sender_type = _marker(markers, "sender_type", KITSU_SYNC_SENDER_TYPE)
    sender_prefix = _marker(markers, "sender_prefix", KITSU_SYNC_SENDER_PREFIX)
    summary_key = _marker(markers, "summary_key", KITSU_SYNC_SUMMARY_KEY)

    for key in _SENDER_TYPE_KEYS:
        if _non_empty_str(event.get(key)) == sender_type:
            return True

    sender = _non_empty_str(event.get("sender"))
    if sender is not None and sender.startswith(sender_prefix):
        return True

    summary = event.get("summary")
    # Only a real boolean ``True`` counts, so a stray truthy value cannot
    # hide a user change.
    if isinstance(summary, dict) and summary.get(summary_key) is True:
        return True

    return False


def classify_origin(event: dict, markers: dict) -> str:
    """Classify where an AYON change came from.

    The check runs in order: an origin marker wins over a user or sender,
    so a Sync_Originated_Change is never treated as a user change
    (Requirements 5.1, 5.12).

    Args:
        event: Event dict with keys ``topic``, ``user``, ``sender``,
            ``senderType`` (or ``sender_type``) and ``summary``. Missing
            keys, a ``None`` or non-dict summary and non-string values are
            treated as absent.
        markers: ``{"sender_type": "kitsu_sync", "sender_prefix":
            "kitsu-processor-", "summary_key": "kitsuSyncOrigin"}``, see
            ``constants.ORIGIN_MARKERS``. A missing or empty marker falls
            back to that default.

    Returns:
        str: ``"sync_originated"`` if any marker matches, ``"user_change"``
        (a person or another integration) if the event has a non-empty
        ``user`` or a non-empty ``sender``, otherwise ``"origin_unknown"``
        (Requirement 5.8).
    """
    if not isinstance(event, dict):
        return ORIGIN_UNKNOWN

    if _has_origin_marker(event, markers):
        return ORIGIN_SYNC_ORIGINATED

    if (
        _non_empty_str(event.get("user")) is not None
        or _non_empty_str(event.get("sender")) is not None
    ):
        return ORIGIN_USER_CHANGE

    return ORIGIN_UNKNOWN


def excluded_at_enrollment(
    topic: str, sender_type: str | None = None
) -> bool:
    """Tell whether a source event is excluded at enrollment.

    True only for creation and deletion topics whose sender type is
    ``kitsu_sync`` (Requirement 5.13).

    Args:
        topic: Event topic string.
        sender_type: Event sender type string, or None.

    Returns:
        bool: True if and only if topic is in ENROLL_EXCLUSION_TOPICS
        and sender_type equals KITSU_SYNC_SENDER_TYPE.
    """
    if topic not in ENROLL_EXCLUSION_TOPICS:
        return False
    return sender_type == KITSU_SYNC_SENDER_TYPE


def build_enroll_filter(topics: list[str]) -> dict | None:
    """Return the enroll QueryFilter dict that implements exclusion.

    Implements ``excluded_at_enrollment`` for the creation and deletion
    topics among ``topics``, or ``None`` when none is enrolled (Requirement
    5.13, F18).

    Args:
        topics: Collection of source topic strings to enroll.

    Returns:
        dict | None: QueryFilter dict with nested OR on topic and sender_type
        under an AND operator, or None if no creation or deletion topic is
        enrolled.
    """
    if not topics:
        return None
    excl = sorted({t for t in topics if t in ENROLL_EXCLUSION_TOPICS})
    if not excl:
        return None
    return {
        "operator": "and",
        "conditions": [
            {
                "operator": "or",
                "conditions": [
                    {"key": "topic", "operator": "ne", "value": topic},
                    {
                        "key": "sender_type",
                        "operator": "ne",
                        "value": KITSU_SYNC_SENDER_TYPE,
                    },
                ],
            }
            for topic in excl
        ],
    }

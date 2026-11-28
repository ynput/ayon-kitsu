"""Constants and pure helpers shared by the Kitsu Server_Addon.

This module must not import anything from ``ayon_server`` so offline tests
can import it.
"""

from typing import Any

# Add Kitsu models that Ayon doesn't have by default.
CONSTANT_KITSU_MODELS: dict[str, dict[str, str]] = {
    "Edit": {
        "shortName": "ed",
        "icon": "cut",
    },
    "Concept": {
        "shortName": "co",
        "icon": "image",
    },
}

# Sender type set on every AYON write that comes from the Kitsu sync.
KITSU_SYNC_SENDER_TYPE = "kitsu_sync"

# Summary key set to True on every event the Server_Addon dispatches.
KITSU_SYNC_SUMMARY_KEY = "kitsuSyncOrigin"

# X-Sender used by Server_Addon REST calls when the request has no sender.
KITSU_SERVER_ADDON_SENDER = "kitsu-server-addon"


def sync_event(**event: Any) -> dict[str, Any]:
    """Mark ``dispatch_event`` keyword arguments as sync originated.

    Sets ``sender_type`` to ``KITSU_SYNC_SENDER_TYPE`` and adds
    ``summary[KITSU_SYNC_SUMMARY_KEY] = True``. Existing summary keys and an
    explicitly passed ``sender`` are kept. The input is not mutated.

    Args:
        **event: Keyword arguments for ``dispatch_event``.

    Returns:
        A new dict with the origin markers added.
    """
    marked = dict(event)
    summary = dict(marked.get("summary") or {})
    summary[KITSU_SYNC_SUMMARY_KEY] = True
    marked["summary"] = summary
    marked["sender_type"] = KITSU_SYNC_SENDER_TYPE
    return marked


def sync_origin_headers(
    session_token: str,
    sender: str | None = None,
) -> dict[str, str]:
    """Build headers for a sync originated AYON REST call.

    Args:
        session_token: AYON session token of the calling user.
        sender: Sender of the current request, if known. Falls back to
            ``KITSU_SERVER_ADDON_SENDER``.

    Returns:
        Headers with ``Authorization``, ``X-Sender`` and ``X-Sender-Type``.
    """
    return {
        "Authorization": f"Bearer {session_token}",
        "X-Sender": sender or KITSU_SERVER_ADDON_SENDER,
        "X-Sender-Type": KITSU_SYNC_SENDER_TYPE,
    }

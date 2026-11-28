"""Attribute parsing and end-frame arithmetic from Kitsu (Requirement 8.7).

This module is pure: it imports only the standard library and performs no
I/O or server database calls. It extracts the parsing logic from
``server/kitsu/anatomy.py`` and the frame arithmetic from
``server/kitsu/utils.py`` so both server endpoints and processor outbound sync
can share them without importing ``ayon_server``.
"""

from __future__ import annotations

import contextlib
from typing import Any, Dict, Optional


def parse_attrib(
    source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Parse AYON attributes from Kitsu entity data (Requirement 8.7).

    Extracts frameStart, frameEnd, fps, resolutionWidth, resolutionHeight,
    description, startDate and endDate from Kitsu data dictionaries.

    Args:
        source: Kitsu entity data dictionary or None.

    Returns:
        Dict mapping AYON attribute names to their parsed values.
    """
    result: Dict[str, Any] = {}
    if source is None:
        return result
    for key, value in source.items():
        if value is None:
            continue

        if key == "fps":
            with contextlib.suppress(ValueError):
                result["fps"] = float(value)
        elif key == "frame_in":
            with contextlib.suppress(ValueError):
                result["frameStart"] = int(value)
        elif key == "frame_out":
            with contextlib.suppress(ValueError):
                result["frameEnd"] = int(value)
        elif key == "resolution" and value:
            try:
                parts = value.split("x")
                result["resolutionWidth"] = int(parts[0])
                result["resolutionHeight"] = int(parts[1])
            except (IndexError, ValueError):
                pass
        elif key == "description":
            result["description"] = value
        elif key == "start_date" and value:
            result["startDate"] = value + "T00:00:00Z"
        elif key == "end_date" and value:
            result["endDate"] = value + "T00:00:00Z"

    return result


def end_frame_from_kitsu(
    entity_dict: Dict[str, Any],
    fallback_frame_start: Optional[int | float] = None,
) -> Optional[int]:
    """Calculate end frame from Kitsu entity data (Requirement 8.7).

    Preserves the pre-refactor behavior of ``utils.calculate_end_frame``:
    - Returns None if "data" is missing or not a dict.
    - Returns "frame_out" directly if truthy. If falsy (e.g. 0, None, ""),
      falls through to calculate from "nb_frames" and frame_in or fallback.
    - If "nb_frames" is truthy and "frame_out" is not truthy:
        Uses data["frame_in"], falling back to fallback_frame_start if None.
        If a start frame is present, returns int(start) + int(nb_frames) - 1.
    - Otherwise returns None.

    Args:
        entity_dict: Kitsu entity dictionary.
        fallback_frame_start: Fallback frame start (e.g. from parent folder).

    Returns:
        The calculated or extracted end frame, or None if not determinable.
    """
    if "data" not in entity_dict or not isinstance(
        entity_dict.get("data"), dict
    ):
        return None

    data = entity_dict["data"]

    # Return end-frame if truthy
    if data.get("frame_out"):
        return data.get("frame_out")

    # Calculate end-frame from nb_frames
    if entity_dict.get("nb_frames") and not data.get("frame_out"):
        frame_start = data.get("frame_in")
        if frame_start is None:
            frame_start = fallback_frame_start
        if frame_start is not None:
            try:
                return (
                    int(frame_start)
                    + int(entity_dict["nb_frames"])
                    - 1
                )
            except (ValueError, TypeError):
                return None

    return None

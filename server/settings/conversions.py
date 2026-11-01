import re
from typing import Any, Optional

# First addon version whose settings contain ``sync_settings.two_way_sync``.
# The feature is developed on ``1.2.7+dev``, so ``1.2.7`` is the first
# release that ships it. Overrides saved by any older version must not carry
# a ``two_way_sync`` entry, so every toggle falls back to its disabled default.
TWO_WAY_SYNC_FIRST_VERSION = (1, 2, 7)

_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)")


def _parse_release(version: str) -> Optional[tuple[int, int, int]]:
    """Parse the ``major.minor.patch`` part of a version string.

    Pre-release (``-rc.1``) and build (``+dev``) suffixes are ignored, so
    ``1.2.7+dev`` and ``1.2.7`` compare as equal.

    Args:
        version: Addon version string, for example ``"1.2.7+dev"``.

    Returns:
        The ``(major, minor, patch)`` tuple, or ``None`` when the string does
        not start with a ``major.minor.patch`` triple.
    """
    match = _VERSION_RE.match(str(version))
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def _convert_two_way_sync(
    source_version: str,
    overrides: dict[str, Any],
) -> None:
    """Drop two-way sync overrides saved by versions without the feature.

    When ``source_version`` is older than ``TWO_WAY_SYNC_FIRST_VERSION``, any
    ``sync_settings.two_way_sync`` key is removed so the disabled defaults
    apply. An unparseable ``source_version`` is treated as older (fail
    closed). No other key is modified.

    Args:
        source_version: Addon version the overrides were saved with.
        overrides: Settings overrides, modified in place.
    """
    release = _parse_release(source_version)
    if release is not None and release >= TWO_WAY_SYNC_FIRST_VERSION:
        return

    sync_settings = overrides.get("sync_settings")
    if isinstance(sync_settings, dict):
        sync_settings.pop("two_way_sync", None)


def _convert_product_base_types(overrides: dict[str, Any]) -> None:
    profiles = (
        overrides
        .get("publish", {})
        .get("CollectKitsuFamily", {})
        .get("profiles")
    )
    if not profiles:
        return

    for profile in profiles:
        if "product_base_types" in profile or "product_types" not in profile:
            return

        profile["product_base_types"] = profile.pop("product_types")


async def convert_settings_overrides(
    source_version: str,
    overrides: dict[str, Any],
) -> dict[str, Any]:
    _convert_two_way_sync(source_version, overrides)
    _convert_product_base_types(overrides)
    return overrides

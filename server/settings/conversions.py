from typing import Any


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
    _convert_product_base_types(overrides)
    return overrides

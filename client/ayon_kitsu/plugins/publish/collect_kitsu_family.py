"""
Requires:
    none

Provides:
    instance     -> families ([])
"""

import pyblish.api

from ayon_core.lib import filter_profiles

from ayon_kitsu.pipeline import plugin


class CollectKitsuFamily(plugin.KitsuPublishInstancePlugin):
    """Adds explicitly 'kitsu' to families to upload instance to FTrack.

    Uses selection by combination of hosts/families/tasks names via
    profiles resolution.

    Triggered everywhere, checks instance against configured.

    Checks advanced filtering which works on 'families' not on main
    'family', as some variants dynamically resolves addition of kitsu
    based on 'families' (editorial drives it by presence of 'review')
    """

    label = "Collect Kitsu Family"
    order = pyblish.api.CollectorOrder + 0.4990

    profiles = None

    def process(self, instance):
        if not self.profiles:
            self.log.warning("No profiles present for adding Kitsu family")
            return

        host_name = instance.context.data["hostName"]
        product_type = instance.data["productType"]
        task_name = instance.data.get("task")

        filtering_criteria = {
            "host_names": host_name,
            "product_types": product_type,
            "task_names": task_name,
        }
        profile = filter_profiles(
            self.profiles, filtering_criteria, logger=self.log
        )

        add_kitsu_family = False
        families = instance.data.setdefault("families", [])

        if profile:
            add_kitsu_family = profile["add_kitsu_family"]
            additional_filters = profile.get("advanced_filtering")
            if additional_filters:
                families_set = set(families) | {product_type}
                self.log.info(
                    "'{}' families used for additional filtering".format(
                        families_set
                    )
                )
                add_kitsu_family = self._get_add_kitsu_f_from_addit_filters(
                    additional_filters, families_set, add_kitsu_family
                )

        result_str = "Not adding"
        if add_kitsu_family:
            result_str = "Adding"
            if "kitsu" not in families:
                families.append("kitsu")

        self.log.debug(
            "{} 'kitsu' family for instance with '{}'".format(
                result_str, product_type
            )
        )

    def _get_add_kitsu_f_from_addit_filters(
        self, additional_filters, families, add_kitsu_family
    ):
        """Compares additional filters - working on instance's families.

        Triggered for more detailed filtering when main family matches,
        but content of 'families' actually matter.
        (For example 'review' in 'families' should result in adding to
        Kitsu)

        Args:
            additional_filters (dict) - from Setting
            families (set[str]) - subfamilies
            add_kitsu_family (bool) - add kitsu to families if True
        """

        override_filter = None
        override_filter_value = -1
        for additional_filter in additional_filters:
            filter_families = set(additional_filter["families"])
            valid = filter_families <= set(families)  # issubset
            if not valid:
                continue

            value = len(filter_families)
            if value > override_filter_value:
                override_filter = additional_filter
                override_filter_value = value

        if override_filter:
            add_kitsu_family = override_filter["add_kitsu_family"]

        return add_kitsu_family

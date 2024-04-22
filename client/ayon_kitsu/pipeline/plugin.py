import pyblish.api
from ayon_core.pipeline.publish import (
    get_plugin_settings,
    apply_plugin_settings_automatically,
)
from ayon_kitsu.addon import is_kitsu_enabled_in_settings

SETTINGS_CATEGORY = "kitsu"


class KitsuPublishContextPlugin(pyblish.api.ContextPlugin):
    settings_category = SETTINGS_CATEGORY

    @classmethod
    def is_kitsu_enabled(cls, project_settings):
        return is_kitsu_enabled_in_settings(
            project_settings.get(SETTINGS_CATEGORY) or {}
        )

    @classmethod
    def apply_settings(cls, project_settings):
        if not cls.is_kitsu_enabled(project_settings):
            cls.enabled = False
            return

        plugin_settins = get_plugin_settings(
            cls, project_settings, cls.log, None
        )
        apply_plugin_settings_automatically(cls, plugin_settins, cls.log)


class KitsuPublishInstancePlugin(pyblish.api.InstancePlugin):
    settings_category = SETTINGS_CATEGORY

    @classmethod
    def is_kitsu_enabled(cls, project_settings):
        return is_kitsu_enabled_in_settings(
            project_settings.get(SETTINGS_CATEGORY) or {}
        )

    @classmethod
    def apply_settings(cls, project_settings):
        if not cls.is_kitsu_enabled(project_settings):
            cls.enabled = False
            return

        plugin_settins = get_plugin_settings(
            cls, project_settings, cls.log, None
        )
        apply_plugin_settings_automatically(cls, plugin_settins, cls.log)

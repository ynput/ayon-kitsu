# -*- coding: utf-8 -*-
import os

import pyblish.api
from ayon_kitsu.pipeline import KitsuPublishContextPlugin
from ayon_kitsu.addon import is_kitsu_enabled_in_settings


class CollectKitsuLogin(KitsuPublishContextPlugin):
    """Collect Kitsu session using user credentials"""

    order = pyblish.api.CollectorOrder
    label = "Kitsu user session"
    # families = ["kitsu"]

    def process(self, context):
        project_settings = context.data["projectSettings"]
        if not is_kitsu_enabled_in_settings(project_settings):
            self.log.info(
                f"Project '{context.data['projectName']} has disabled Kitsu"
            )
            return

        import gazu

        gazu.set_host(os.environ["KITSU_SERVER"])
        gazu.log_in(os.environ["KITSU_LOGIN"], os.environ["KITSU_PWD"])

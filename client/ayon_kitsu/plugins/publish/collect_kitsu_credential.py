# -*- coding: utf-8 -*-
import os

import pyblish.api
from ayon_kitsu.pipeline import KitsuPublishContextPlugin


class CollectKitsuLogin(KitsuPublishContextPlugin):
    """Collect Kitsu session using user credentials"""

    order = pyblish.api.CollectorOrder
    label = "Kitsu user session"
    # families = ["kitsu"]

    def process(self, context):
        import gazu

        gazu.set_host(os.environ["KITSU_SERVER"])
        gazu.log_in(os.environ["KITSU_LOGIN"], os.environ["KITSU_PWD"])

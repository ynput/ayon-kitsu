"""
Handle Events originated from Kitsu.
"""

from typing import Union

from kitsu_common.ayon_kitsu_hub import AyonKitsuHub
from nxtools import logging

REGISTER_EVENT_TYPE = ["kitsu-new_project"]


def process_event(
    kitsu_server_url: str,
    kitsu_login_email: str,
    kitsu_login_password: str,
    user_name: Union[str, None] = None,
    project_name: Union[str, None] = None,
    project_code: Union[str, None] = None,
    project_code_field: Union[str, None] = None,
    kitsu_payload: Union[str, None] = None,
    **kwargs,
):
    """React to Kitsu Events.

    Events with the action `kitsu-event` will trigger this
    function, where we attempt to replicate a change coming from Kitsu, like
    creating a new Shot, renaming a Task, etc.
    """

    if not kitsu_payload:
        logging.error("The Event payload is empty!")
        raise ValueError("The Event payload is empty!")
    print(
        project_name,
        project_code,
        kitsu_server_url,
        kitsu_login_email,
        kitsu_login_password,
    )

    hub = AyonKitsuHub(
        project_name,
        project_code,
        kitsu_server_url,
        kitsu_login_email,
        kitsu_login_password,
    )

    hub.create_project(kitsu_payload)

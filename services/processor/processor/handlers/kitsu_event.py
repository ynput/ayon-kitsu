"""
Handle Events originated from Kitsu.
"""

from kitsu_common.ayon_kitsu_hub import AyonKitsuHub
from nxtools import logging

REGISTER_EVENT_TYPE = ["kitsu-event"]


def process_event(
    kitsu_server_url: str,
    kitsu_login_email: str,
    kitsu_login_password: str,
    project_name: str,
    project_code: str,
    kitsu_payload: dict[str, str],
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

    hub = AyonKitsuHub(
        project_name,
        project_code,
        kitsu_server_url,
        kitsu_login_email,
        kitsu_login_password,
    )

    hub.react_to_kitsu_event(kitsu_payload)

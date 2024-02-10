from typing import TYPE_CHECKING

import gazu
from nxtools import slugify

from kitsu_common.utils import (
    get_entity_by_kitsu_id,
    get_or_create_root_folder_by_name,
    parse_attrib,
)

if TYPE_CHECKING:
    from ayon_api.entity_hub import EntityHub


def kitsu_sequence_new(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    kitsu_sequence = gazu.shot.get_sequence(kitsu_event["sequence_id"])
    root = get_or_create_root_folder_by_name(ay_project, "Sequence")
    folder = ay_project.add_new_folder(
        folder_type="Sequence",
        name=slugify(kitsu_sequence["name"], separator="_", lower=False),
        label=kitsu_sequence["name"],
        parent_id=root.id,
        data={"kitsuId": kitsu_sequence["id"]},
        attribs=parse_attrib(kitsu_sequence),
    )

    # Add ayon ID to the sequence's data in Kitsu so we later can fetch it directly
    if kitsu_sequence["data"] is None:
        kitsu_sequence["data"] = {}
    kitsu_sequence["data"]["ayon_id"] = folder.id
    gazu.shot.update_sequence(kitsu_sequence)


def kitsu_sequence_update(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    kitsu_sequence = gazu.shot.get_sequence(kitsu_event["sequence_id"])
    ay_folder = ay_project.get_folder_by_id(kitsu_sequence["data"]["ayon_id"])
    ay_folder.name = kitsu_sequence["name"]
    for key, value in parse_attrib(kitsu_sequence).items():
        ay_folder.attribs[key] = value


def kitsu_sequence_delete(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    ayon_sequence = get_entity_by_kitsu_id(kitsu_event["sequence_id"], ay_project)
    if ayon_sequence:
        ayon_sequence.parent.remove_child(ayon_sequence)

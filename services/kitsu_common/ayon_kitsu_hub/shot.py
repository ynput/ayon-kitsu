from pprint import pprint
from typing import TYPE_CHECKING

import gazu
from nxtools import slugify

from kitsu_common.utils import get_entity_by_kitsu_id, parse_attrib

if TYPE_CHECKING:
    from ayon_api.entity_hub import EntityHub


def kitsu_shot_new(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    kitsu_shot = gazu.shot.get_shot(kitsu_event["shot_id"])
    kitsu_sequence = gazu.shot.get_sequence(kitsu_shot["sequence_id"])
    print("----------")
    pprint(kitsu_shot)
    print("---------")
    folder = ay_project.add_new_folder(
        folder_type="Sequence",
        name=slugify(kitsu_shot["name"], separator="_", lower=False),
        label=kitsu_shot["name"],
        parent_id=kitsu_sequence["data"]["ayon_id"],
        data={"kitsuId": kitsu_shot["id"]},
        attribs=parse_attrib(kitsu_shot),
    )

    # TODO As Kitsu have nb_frames instead of start/end frame we need to calculate the endFrame from nb_frames + startFrame

    # Add ayon ID to the shot's data in Kitsu so we later can fetch it directly
    if kitsu_shot["data"] is None:
        kitsu_shot["data"] = {}
    kitsu_shot["data"]["ayon_id"] = folder.id
    gazu.shot.update_shot(kitsu_shot)


def kitsu_shot_update(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    kitsu_shot = gazu.shot.get_shot(kitsu_event["shot_id"])
    ay_folder = ay_project.get_folder_by_id(kitsu_shot["data"]["ayon_id"])
    ay_folder.name = kitsu_shot["name"]
    # TODO As Kitsu have nb_frames instead of start/end frame we need to calculate the endFrame from nb_frames + startFrame
    for key, value in parse_attrib(kitsu_shot).items():
        ay_folder.attribs[key] = value


def kitsu_shot_delete(
    kitsu_event: dict[str, str],
    ay_project: "EntityHub",
):
    ayon_shot = get_entity_by_kitsu_id(kitsu_event["shot_id"], ay_project)
    if ayon_shot:
        ayon_shot.parent.remove_child(ayon_shot)

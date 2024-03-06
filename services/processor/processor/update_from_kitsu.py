from typing import TYPE_CHECKING

import ayon_api
import gazu
from nxtools import logging

from . import utils

if TYPE_CHECKING:
    from .processor import KitsuProcessor


def update_project(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"update_project: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get asset entity
    entity = gazu.project.get_project(data["project_id"])

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_project(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_project: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Add ayon base url so we can use it in REST calls later on
    entity = {}

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_asset(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_asset: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get asset entity
    entity = gazu.asset.get_asset(data["asset_id"])
    entity = utils.preprocess_asset(entity["project_id"], entity)

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_asset(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_asset: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["asset_id"],
        "type": "Asset",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_episode(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_episode: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired
    # Get episode entity
    entity = gazu.shot.get_episode(data["episode_id"])

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_episode(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_episode: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["episode_id"],
        "type": "Episode",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_sequence(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_sequence: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = gazu.shot.get_sequence(data["sequence_id"])

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_sequence(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_sequence: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["sequence_id"],
        "type": "Sequence",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_shot(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_shot: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = gazu.shot.get_shot(data["shot_id"])

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_shot(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_shot: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["shot_id"],
        "type": "Shot",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_task(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_task: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = gazu.task.get_task(data["task_id"])
    entity = utils.preprocess_task(entity["project_id"], entity)

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_task(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_task: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["task_id"],
        "type": "Task",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_edit(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_edit: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get edit entity
    entity = gazu.edit.get_edit(data["edit_id"])

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_edit(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_edit: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["edit_id"],
        "type": "Edit",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_concept(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_concept: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    # Get concept entity
    entity = gazu.concept.get_concept(data["concept_id"])

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name=project_name,
        entities=[entity],
    )


def delete_concept(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_concept: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["concept_id"],
        "type": "Concept",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )


def create_or_update_person(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"create_or_update_person: {data}")
    entity = gazu.person.get_person(data["person_id"])

    return ayon_api.post(
        f"{parent.entrypoint}/push",
        project_name="",
        entities=[entity],
    )


def delete_person(parent: "KitsuProcessor", data: dict[str, str]):
    logging.info(f"delete_person: {data}")
    project_name = parent.get_paired_ayon_project(data["project_id"])
    if not project_name:
        return  # do nothing as this kitsu and ayon project are not paired

    entity = {
        "id": data["person_id"],
        "type": "person",
    }
    return ayon_api.post(
        f"{parent.entrypoint}/remove",
        project_name=project_name,
        entities=[entity],
    )

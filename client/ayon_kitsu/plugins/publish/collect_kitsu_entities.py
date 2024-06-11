# -*- coding: utf-8 -*-
import gazu
import pyblish.api

from ayon_core.pipeline import KnownPublishError
from ayon_kitsu.pipeline import KitsuPublishContextPlugin
from ayon_kitsu.addon import is_kitsu_enabled_in_settings


class CollectKitsuEntities(KitsuPublishContextPlugin):
    """Collect Kitsu entities according to the current context"""

    order = pyblish.api.CollectorOrder + 0.499
    label = "Kitsu entities"

    def process(self, context):
        project_settings = context.data["project_settings"]
        if not is_kitsu_enabled_in_settings(project_settings):
            self.log.info(
                f"Project '{context.data['projectName']} has disabled Kitsu"
            )
            return

        project_entity = context.data["projectEntity"]
        project_id = project_entity["data"].get("kitsuProjectId")
        kitsu_project = None
        if project_id:
            kitsu_project = gazu.project.get_project(project_id)
        if not kitsu_project:
            project_name = context.data["projectName"]
            raise KnownPublishError(
                f"Project '{project_name}' not found in kitsu by id!"
            )

        context.data["kitsuProject"] = kitsu_project
        self.log.debug(f"Collect kitsu project: {kitsu_project}")

        filtered_instances = []
        for instance in context:
            folder_entity = instance.data.get("folderEntity")
            if folder_entity:
                filtered_instances.append(instance)

        if not filtered_instances:
            return

        kitsu_entities_by_id = {}
        for instance in filtered_instances:
            folder_entity = instance.data["folderEntity"]
            folder_path = folder_entity["path"]
            kitsu_id = folder_entity["data"].get("kitsuId")
            if not kitsu_id:
                raise KnownPublishError(
                    f"Kitsu id not available in AYON for '{folder_path}'"
                )

            kitsu_entity = kitsu_entities_by_id.get(kitsu_id)
            if not kitsu_entity:
                kitsu_entity = gazu.entity.get_entity(kitsu_id)
                if not kitsu_entity:
                    raise KnownPublishError(
                        f"{folder_path} was not found in kitsu!"
                    )
                kitsu_entities_by_id[kitsu_id] = kitsu_entity

            instance.data["kitsuEntity"] = kitsu_entity

            # Task entity
            task_entity = instance.data.get("taskEntity")
            if not task_entity:
                continue

            task_name = task_entity["name"]
            kitsu_task_id = task_entity["data"].get("kitsuId")

            self.log.debug(f"Collect kitsu: {kitsu_entity}")

            if kitsu_task_id:
                kitsu_task = kitsu_entities_by_id.get(
                    kitsu_task_id
                ) or gazu.task.get_task(kitsu_task_id)
            else:
                kitsu_task_type = gazu.task.get_task_type_by_name(task_name)
                if not kitsu_task_type:
                    raise KnownPublishError(
                        f"Task type {task_name} not found in Kitsu!"
                    )

                kitsu_task = gazu.task.get_task_by_name(
                    kitsu_entity, kitsu_task_type
                )

            if not kitsu_task:
                raise KnownPublishError(
                    f"Task {task_name} not found in kitsu!"
                )

            kitsu_entities_by_id[kitsu_task["id"]] = kitsu_task

            instance.data["kitsuTask"] = kitsu_task
            self.log.debug(f"Collect kitsu task: {kitsu_task}")

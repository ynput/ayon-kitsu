"""
A Kitsu Events listener leecher for Ayon.

This service will continually run and listen for any Gazu events
Kitsu and converts them to Ayon events, and can be configured from the Ayon
Addon settings page.
"""

import inspect
import os
import socket
import sys
import time
from pprint import pprint
from typing import Any

import ayon_api
import gazu
from kitsu_common.utils import (
    KitsuServerError,
    get_asset_types,
    get_kitsu_credentials,
    get_statuses,
    get_task_types,
)
from nxtools import log_traceback, logging

# from .update_op_with_zou import (
#    create_op_asset,
#    get_kitsu_project_name,
#    set_op_project,
#    update_op_assets,
#    write_project_to_op,
# )

if service_name := os.environ.get("AYON_SERVICE_NAME"):
    logging.user = service_name


class KitsuListener:
    """Host Kitsu listener."""

    def __init__(self):
        #
        # Connect to Ayon
        #

        try:
            ayon_api.init_service()
            connected = True
        except Exception:
            log_traceback()
            connected = False

        if not connected:
            print("Kitsu Leecher failed to connect to Ayon")
            # Sleep for 10 seconds, so it is possible to see the message in
            #   docker
            # NOTE: Becuase AYON connection failed, there's no way how to log it
            #   to AYON server (obviously)... So stdout is all we have.
            time.sleep(10)
            sys.exit(1)

        #
        # Load settings and stuff...
        #

        self.addon_name = ayon_api.get_service_addon_name()
        self.addon_version = ayon_api.get_service_addon_version()
        self.settings = ayon_api.get_service_addon_settings()
        self.entrypoint = f"/addons/{self.addon_name}/{self.addon_version}"
        self.kitsu_server_url, self.kitsu_login_email, self.kitsu_login_password = (
            get_kitsu_credentials(ayon_api, self.settings)
        )

        #
        # Connect to Kitsu
        #

        gazu.set_host(self.kitsu_server_url)
        if not gazu.client.host_is_valid():
            raise KitsuServerError(
                f"Kitsu server `{self.kitsu_server_url}` is not valid"
            )

        try:
            gazu.log_in(self.kitsu_login_email, self.kitsu_login_password)
        except gazu.exception.AuthFailedException as e:
            raise KitsuServerError(f"Kitsu login failed: {e}") from e

        #
        # Set all listeners
        #

        self.set_listeners()

    def set_listeners(self):
        logging.info("Initializing the Kitsu Listeners.")

        gazu.set_event_host(self.kitsu_server_url.replace("/api", ""))
        self.event_client = gazu.events.init()

        gazu.events.add_listener(self.event_client, "project:new", self._new_project)
        gazu.events.add_listener(
            self.event_client, "project:update", self._update_project
        )
        gazu.events.add_listener(
            self.event_client, "project:delete", self._delete_project
        )

        gazu.events.add_listener(self.event_client, "asset:new", self._new_asset)
        gazu.events.add_listener(self.event_client, "asset:update", self._update_asset)
        gazu.events.add_listener(self.event_client, "asset:delete", self._delete_asset)

        gazu.events.add_listener(self.event_client, "episode:new", self._new_episode)
        gazu.events.add_listener(
            self.event_client, "episode:update", self._update_episode
        )
        gazu.events.add_listener(
            self.event_client, "episode:delete", self._delete_episode
        )

        gazu.events.add_listener(self.event_client, "sequence:new", self._new_sequence)
        gazu.events.add_listener(
            self.event_client, "sequence:update", self._update_sequence
        )
        gazu.events.add_listener(
            self.event_client, "sequence:delete", self._delete_sequence
        )

        gazu.events.add_listener(self.event_client, "shot:new", self._new_shot)
        gazu.events.add_listener(self.event_client, "shot:update", self._update_shot)
        gazu.events.add_listener(self.event_client, "shot:delete", self._delete_shot)

        gazu.events.add_listener(self.event_client, "task:new", self._new_task)
        gazu.events.add_listener(self.event_client, "task:update", self._update_task)
        gazu.events.add_listener(self.event_client, "task:delete", self._delete_task)

    def start_listening(self):
        """Start listening for events."""
        logging.info("Listening to Kitsu events...")
        gazu.events.run_client(self.event_client)

    def get_ep_dict(self, ep_id):
        print(inspect.stack()[0][3])
        return
        if ep_id and ep_id != "":
            return gazu.entity.get_entity(ep_id)
        return

    # == Project ==
    def _new_project(self, data):
        """Create new project into OP DB."""
        print(inspect.stack()[0][3])
        data["event_type"] = "project:new"
        self.send_kitsu_event_to_ayon(data, event_type="kitsu-new_project")
        return
        # Use update process to avoid duplicating code
        self._update_project(data, new_project=True)

    def _update_project(self, data, new_project=False):
        print(inspect.stack()[0][3])
        return
        """Update project into OP DB."""
        # Get project entity
        project = gazu.project.get_project(data["project_id"])

        update_project = write_project_to_op(project, self.dbcon)

        # Write into DB
        if update_project:
            self.dbcon.Session["AVALON_PROJECT"] = get_kitsu_project_name(
                data["project_id"]
            )
            self.dbcon.bulk_write([update_project])

            if new_project:
                logging.info("Project created: {}".format(project["name"]))

    def _delete_project(self, data):
        print(inspect.stack()[0][3])
        return
        """Delete project."""

        collections = self.dbcon.database.list_collection_names()
        for collection in collections:
            project = self.dbcon.database[collection].find_one(
                {"data.zou_id": data["project_id"]}
            )
            if project:
                # Delete project collection
                self.dbcon.database[project["name"]].drop()

                # Print message
                logging.info("Project deleted: {}".format(project["name"]))
                return

    # == Asset ==
    def _new_asset(self, data):
        print(inspect.stack()[0][3])
        return
        """Create new asset into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get asset entity
        asset = gazu.asset.get_asset(data["asset_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(asset))

        # Update
        self._update_asset(data)

        # Print message
        ep_id = asset.get("episode_id")
        ep = self.get_ep_dict(ep_id)

        msg = (
            "Asset created: {proj_name} - {ep_name}"
            "{asset_type_name} - {asset_name}".format(
                proj_name=asset["project_name"],
                ep_name=ep["name"] + " - " if ep is not None else "",
                asset_type_name=asset["asset_type_name"],
                asset_name=asset["name"],
            )
        )
        logging.info(msg)

    def _update_asset(self, data):
        print(inspect.stack()[0][3])
        return
        """Update asset into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        asset = gazu.asset.get_asset(data["asset_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[asset["project_id"]] = project_doc
        gazu_project = gazu.project.get_project(asset["project_id"])

        # Update
        update_op_result = update_op_assets(
            self.dbcon,
            gazu_project,
            project_doc,
            [asset],
            zou_ids_and_asset_docs,
        )
        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_asset(self, data):
        print(inspect.stack()[0][3])
        return
        """Delete asset of OP DB."""
        set_op_project(self.dbcon, data["project_id"])

        asset = self.dbcon.find_one({"data.zou.id": data["asset_id"]})
        if asset:
            # Delete
            self.dbcon.delete_one({"type": "asset", "data.zou.id": data["asset_id"]})

            # Print message
            ep_id = asset["data"]["zou"].get("episode_id")
            ep = self.get_ep_dict(ep_id)

            msg = (
                "Asset deleted: {proj_name} - {ep_name}"
                "{type_name} - {asset_name}".format(
                    proj_name=asset["data"]["zou"]["project_name"],
                    ep_name=ep["name"] + " - " if ep is not None else "",
                    type_name=asset["data"]["zou"]["asset_type_name"],
                    asset_name=asset["name"],
                )
            )
            logging.info(msg)

    # == Episode ==
    def _new_episode(self, data):
        print(inspect.stack()[0][3])
        return
        """Create new episode into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get gazu entity
        ep = gazu.shot.get_episode(data["episode_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(ep))

        # Update
        self._update_episode(data)

        # Print message
        msg = "Episode created: {proj_name} - {ep_name}".format(
            proj_name=ep["project_name"], ep_name=ep["name"]
        )
        logging.info(msg)

    def _update_episode(self, data):
        print(inspect.stack()[0][3])
        return
        """Update episode into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        ep = gazu.shot.get_episode(data["episode_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[ep["project_id"]] = project_doc
        gazu_project = gazu.project.get_project(ep["project_id"])

        # Update
        update_op_result = update_op_assets(
            self.dbcon,
            gazu_project,
            project_doc,
            [ep],
            zou_ids_and_asset_docs,
        )
        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_episode(self, data):
        print(inspect.stack()[0][3])
        return
        """Delete shot of OP DB."""
        set_op_project(self.dbcon, data["project_id"])

        ep = self.dbcon.find_one({"data.zou.id": data["episode_id"]})
        if ep:
            # Delete
            self.dbcon.delete_one({"type": "asset", "data.zou.id": data["episode_id"]})

            # Print message
            project = gazu.project.get_project(ep["data"]["zou"]["project_id"])

            msg = "Episode deleted: {proj_name} - {ep_name}".format(
                proj_name=project["name"], ep_name=ep["name"]
            )
            logging.info(msg)

    # == Sequence ==
    def _new_sequence(self, data):
        print(inspect.stack()[0][3])
        return
        """Create new sequnce into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get gazu entity
        sequence = gazu.shot.get_sequence(data["sequence_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(sequence))

        # Update
        self._update_sequence(data)

        # Print message
        ep_id = sequence.get("episode_id")
        ep = self.get_ep_dict(ep_id)

        msg = "Sequence created: {proj_name} - {ep_name}" "{sequence_name}".format(
            proj_name=sequence["project_name"],
            ep_name=ep["name"] + " - " if ep is not None else "",
            sequence_name=sequence["name"],
        )
        logging.info(msg)

    def _update_sequence(self, data):
        print(inspect.stack()[0][3])
        return
        """Update sequence into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        sequence = gazu.shot.get_sequence(data["sequence_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[sequence["project_id"]] = project_doc
        gazu_project = gazu.project.get_project(sequence["project_id"])

        # Update
        update_op_result = update_op_assets(
            self.dbcon,
            gazu_project,
            project_doc,
            [sequence],
            zou_ids_and_asset_docs,
        )
        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_sequence(self, data):
        print(inspect.stack()[0][3])
        return
        """Delete sequence of OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        sequence = self.dbcon.find_one({"data.zou.id": data["sequence_id"]})
        if sequence:
            # Delete
            self.dbcon.delete_one({"type": "asset", "data.zou.id": data["sequence_id"]})

            # Print message
            ep_id = sequence["data"]["zou"].get("episode_id")
            ep = self.get_ep_dict(ep_id)

            gazu_project = gazu.project.get_project(
                sequence["data"]["zou"]["project_id"]
            )

            msg = "Sequence deleted: {proj_name} - {ep_name}" "{sequence_name}".format(
                proj_name=gazu_project["name"],
                ep_name=ep["name"] + " - " if ep is not None else "",
                sequence_name=sequence["name"],
            )
            logging.info(msg)

    # == Shot ==
    def _new_shot(self, data):
        print(inspect.stack()[0][3])
        return
        """Create new shot into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])

        # Get gazu entity
        shot = gazu.shot.get_shot(data["shot_id"])

        # Insert doc in DB
        self.dbcon.insert_one(create_op_asset(shot))

        # Update
        self._update_shot(data)

        # Print message
        ep_id = shot["episode_id"]
        ep = self.get_ep_dict(ep_id)

        msg = (
            "Shot created: {proj_name} - {ep_name}"
            "{sequence_name} - {shot_name}".format(
                proj_name=shot["project_name"],
                ep_name=ep["name"] + " - " if ep is not None else "",
                sequence_name=shot["sequence_name"],
                shot_name=shot["name"],
            )
        )
        logging.info(msg)

    def _update_shot(self, data):
        print(inspect.stack()[0][3])
        return
        """Update shot into OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        project_doc = get_project(project_name)

        # Get gazu entity
        shot = gazu.shot.get_shot(data["shot_id"])

        # Find asset doc
        # Query all assets of the local project
        zou_ids_and_asset_docs = {
            asset_doc["data"]["zou"]["id"]: asset_doc
            for asset_doc in get_assets(project_name)
            if asset_doc["data"].get("zou", {}).get("id")
        }
        zou_ids_and_asset_docs[shot["project_id"]] = project_doc
        gazu_project = gazu.project.get_project(shot["project_id"])

        # Update
        update_op_result = update_op_assets(
            self.dbcon,
            gazu_project,
            project_doc,
            [shot],
            zou_ids_and_asset_docs,
        )

        if update_op_result:
            asset_doc_id, asset_update = update_op_result[0]
            self.dbcon.update_one({"_id": asset_doc_id}, asset_update)

    def _delete_shot(self, data):
        print(inspect.stack()[0][3])
        return
        """Delete shot of OP DB."""
        set_op_project(self.dbcon, data["project_id"])
        shot = self.dbcon.find_one({"data.zou.id": data["shot_id"]})

        if shot:
            # Delete
            self.dbcon.delete_one({"type": "asset", "data.zou.id": data["shot_id"]})

            # Print message
            ep_id = shot["data"]["zou"].get("episode_id")
            ep = self.get_ep_dict(ep_id)

            msg = (
                "Shot deleted: {proj_name} - {ep_name}"
                "{sequence_name} - {shot_name}".format(
                    proj_name=shot["data"]["zou"]["project_name"],
                    ep_name=ep["name"] + " - " if ep is not None else "",
                    sequence_name=shot["data"]["zou"]["sequence_name"],
                    shot_name=shot["name"],
                )
            )
            logging.info(msg)

    # == Task ==
    def _new_task(self, data):
        print(inspect.stack()[0][3])
        data["event_type"] = "task:new"
        self.send_kitsu_event_to_ayon(data)
        return
        """Create new task into OP DB."""
        # Get project entity
        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()

        # Get gazu entity
        task = gazu.task.get_task(data["task_id"])

        # Print message
        ep_id = task.get("episode_id")
        ep = self.get_ep_dict(ep_id)

        parent_name = None
        asset_name = None
        ent_type = None

        if task["task_type"]["for_entity"] == "Asset":
            parent_name = task["entity"]["name"]
            asset_name = task["entity"]["name"]
            ent_type = task["entity_type"]["name"]
        elif task["task_type"]["for_entity"] == "Shot":
            parent_name = "{ep_name}{sequence_name} - {shot_name}".format(
                ep_name=ep["name"] + " - " if ep is not None else "",
                sequence_name=task["sequence"]["name"],
                shot_name=task["entity"]["name"],
            )
            asset_name = "{ep_name}{sequence_name}_{shot_name}".format(
                ep_name=ep["name"] + "_" if ep is not None else "",
                sequence_name=task["sequence"]["name"],
                shot_name=task["entity"]["name"],
            )

        # Update asset tasks with new one
        asset_doc = get_asset_by_name(project_name, asset_name)
        if asset_doc:
            asset_tasks = asset_doc["data"].get("tasks")
            task_type_name = task["task_type"]["name"]
            asset_tasks[task_type_name] = {
                "type": task_type_name,
                "zou": task,
            }
            self.dbcon.update_one(
                {"_id": asset_doc["_id"]},
                {"$set": {"data.tasks": asset_tasks}},
            )

            # Print message
            msg = "Task created: {proj} - {ent_type}{parent}" " - {task}".format(
                proj=task["project"]["name"],
                ent_type=ent_type + " - " if ent_type is not None else "",
                parent=parent_name,
                task=task["task_type"]["name"],
            )
            logging.info(msg)

    def _update_task(self, data):
        """Update task into OP DB."""

        asset_types = get_asset_types(data["project_id"])
        task_types = get_task_types(data["project_id"])
        task_statuses = get_statuses()

        episodes = gazu.shot.all_episodes_for_project(data["project_id"])
        seqs = gazu.shot.all_sequences_for_project(data["project_id"])
        shots = gazu.shot.all_shots_for_project(data["project_id"])

        assets = []

        for record in gazu.asset.all_assets_for_project(data["project_id"]):
            asset = {
                **record,
                "asset_type_name": asset_types[record["entity_type_id"]],
            }
            assets.append(asset)

        tasks = []
        for record in gazu.task.all_tasks_for_project(data["project_id"]):
            task = {
                **record,
                "task_type_name": task_types[record["task_type_id"]],
                "task_status_name": task_statuses[record["task_status_id"]],
            }
            if record["name"] == "main":
                task["name"] = task["task_type_name"].lower()
            tasks.append(task)

        # TODO: replace user uuids in task.assigness with emails
        # which can be used to pair with ayon users

        # compile list of entities
        # TODO: split folders and tasks if the list is huge

        entities = assets + episodes + seqs + shots + tasks
        # print(gazu.project.get_project(data["project_id"]["name"]))
        # pprint("-1-----------------------")
        # pprint(entities)
        # pprint("-2-----------------------")
        # pprint(
        #    ayon_api.get_project(
        #        gazu.project.get_project(
        #            data["project_id"],
        #        )["name"],
        #    )
        # )
        # pprint("-3-----------------------")
        data["event_type"] = "task:update"
        self.send_kitsu_event_to_ayon(data)

    def _delete_task(self, data):
        print(inspect.stack()[0][3])
        return
        """Delete task of OP DB."""

        set_op_project(self.dbcon, data["project_id"])
        project_name = self.dbcon.active_project()
        # Find asset doc
        asset_docs = list(get_assets(project_name))
        for doc in asset_docs:
            # Match task
            for name, task in doc["data"]["tasks"].items():
                if task.get("zou") and data["task_id"] == task["zou"]["id"]:
                    # Pop task
                    asset_tasks = doc["data"].get("tasks", {})
                    asset_tasks.pop(name)

                    # Delete task in DB
                    self.dbcon.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"data.tasks": asset_tasks}},
                    )

                    # Print message
                    entity = gazu.entity.get_entity(task["zou"]["entity_id"])
                    ep = self.get_ep_dict(entity["source_id"])

                    if entity["type"] == "Asset":
                        parent_name = "{ep}{entity_type} - {entity}".format(
                            ep=ep["name"] + " - " if ep is not None else "",
                            entity_type=task["zou"]["entity_type"]["name"],
                            entity=task["zou"]["entity"]["name"],
                        )
                    elif entity["type"] == "Shot":
                        parent_name = "{ep}{sequence} - {shot}".format(
                            ep=ep["name"] + " - " if ep is not None else "",
                            sequence=task["zou"]["sequence"]["name"],
                            shot=task["zou"]["entity"]["name"],
                        )

                    msg = "Task deleted: {proj} - {parent} - {task}".format(
                        proj=task["zou"]["project"]["name"],
                        parent=parent_name,
                        task=name,
                    )
                    logging.info(msg)

                    return

    def send_kitsu_event_to_ayon(
        self, payload: dict[str, Any], event_type: str = "kitsu-event"
    ):
        """Send the Kitsu event as an Ayon event.

        Args:
            payload (dict): The Event data.
        """

        logging.info(f"Processing Kitsu Event {payload}")
        description = f"Leeched {payload['event_type']}"
        logging.info(description)

        project_name = gazu.project.get_project(payload["project_id"])["name"]

        logging.info(f"Event is from Project {project_name} ({payload['project_id']})")

        ayon_api.dispatch_event(
            "kitsu.event",
            sender=socket.gethostname(),
            project_name=project_name,
            description=description,
            summary=None,
            payload={
                "action": event_type,
                "kitsu_payload": payload,
                "project_name": project_name,
            },
        )
        logging.info("Dispatched Ayon event ", payload["event_type"])

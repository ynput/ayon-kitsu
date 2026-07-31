from pathlib import Path
from typing import Optional
import webbrowser
import ayon_api
import gazu

from ayon_core.pipeline import LauncherAction
from ayon_core.addon import AddonsManager


class ShowInKitsu(LauncherAction):
    name = "showinkitsu"
    label = "Show in Kitsu"
    icon = "external-link-square"
    color = "#e0e1e1"
    order = 10

    @staticmethod
    def get_kitsu_addon():
        return AddonsManager().get("kitsu")

    def is_compatible(self, selection):
        return selection.is_project_selected

    def process(self, selection, **kwargs):
        # Context inputs
        project_name = selection.project_name
        project = ayon_api.get_project(project_name)
        if not project:
            raise RuntimeError(f"Project {project_name} not found.")

        folder = (
            selection.folder_entity
            if selection.is_folder_selected
            else None
        )
        task = selection.task_entity if selection.is_task_selected else None
        if message := self._get_unavailable_message(project, folder, task):
            self.get_kitsu_addon().show_tray_message(
                "Show in Kitsu unavailable",
                message,
            )
            return

        # Define URL
        url = self.get_url(project, folder, task)

        # Open URL in webbrowser
        self.log.info(f"Opening URL: {url}")
        webbrowser.open(
            url,
            # Try in new tab
            new=2,
        )

    @staticmethod
    def _get_unavailable_message(
        project: dict,
        folder: dict = None,
        task: dict = None,
    ) -> Optional[str]:
        """Return an artist-facing explanation for unavailable Kitsu links."""
        if not project.get("data", {}).get("kitsuProjectId"):
            return (
                f"'{project['name']}' is not connected to Kitsu. "
                "Ask your project administrator to connect the project."
            )

        if task and not task.get("data", {}).get("kitsuId"):
            return (
                f"The task '{task['name']}' is not connected to a Kitsu task. "
                "Select a synced task or ask your project administrator "
                "for help."
            )

        if folder and not folder.get("data", {}).get("kitsuId"):
            return (
                f"The folder '{folder['name']}' is not connected to Kitsu. "
                "Select a synced folder or ask your project administrator "
                "for help."
            )
        return None

    def get_url(
        self,
        project: dict,
        folder: dict = None,
        task: dict = None,
    ) -> str:
        """Get the URL for the project, folder, or task.

        Args:
            project (dict): The project data.
            folder (dict): The folder data.
            task (dict): The task data.

        Returns:
            str: The URL for the project, folder, or task.
        """
        if not (project_kitsu_id := project["data"].get("kitsuProjectId")):
            raise RuntimeError(
                f"Project {project['name']} has no connected kitsu id."
            )
        project_url = Path(
            gazu.project.get_project_url({"id": project_kitsu_id})
        )

        if task:
            if not (task_id := task.get("data", {}).get("kitsuId")):
                raise RuntimeError(
                    f"Task {task['name']} has no connected kitsu entity."
                )

            return gazu.task.get_task_url(
                {"project_id": project_kitsu_id, "id": task_id}
            )
        elif folder:
            folder_type = folder["folderType"]
            folder_path = Path(folder["path"])
            if not (kitsu_id := folder["data"].get("kitsuId")):
                raise RuntimeError(
                    f"Folder {folder['name']} has no connected kitsu entity."
                )

            if folder_type == "Folder":
                if len(folder_path.parents) == 1:  # Root folder
                    return f"{project_url.parent}/{folder['name']}"
                elif len(folder_path.parents) == 2:  # Asset type
                    return self._get_asset_type_url(
                        project_kitsu_id, folder["label"]
                    )
                else:  # Asset
                    return gazu.asset.get_asset_url(
                        {"project_id": project_kitsu_id, "id": kitsu_id}
                    )
            elif folder_type == "Sequence":
                return self._get_sequence_url(
                    project, project_kitsu_id, kitsu_id, folder_path
                )
            elif folder_type == "Episode":
                return gazu.shot.get_episode_url(
                    {"project_id": project_kitsu_id, "id": kitsu_id}
                )
            elif folder_type == "Shot":
                return gazu.shot.get_shot_url(
                    {"project_id": project_kitsu_id, "id": kitsu_id}
                )
            else:
                return (
                    f"{project_url.parent}/{folder_type.lower()}s/{kitsu_id}"
                )
        else:
            return project_url.as_posix()

    def _get_asset_type_url(
        self, project_kitsu_id: str, folder_label: str
    ) -> str:
        """Get the URL for the asset type page.

        Meant to be replaced by gazu.asset.get_asset_type_url when available.
        See https://github.com/cgwire/gazu/issues/392
        """
        project_url = Path(
            gazu.project.get_project_url({"id": project_kitsu_id})
        )
        return (
            f"{project_url.parent}/episodes/all/assets"
            f"?search=+type=[{folder_label}]"
        )

    def _get_sequence_url(
        self,
        project: dict,
        project_kitsu_id: str,
        kitsu_id: str,
        folder_path: Path,
    ) -> str:
        """Get the URL for the sequence page.

        Meant to be replaced by gazu.shot.get_sequence_url when available.
        See https://github.com/cgwire/gazu/issues/392
        """
        if folder_path.parts[1] == "episodes":
            episode_folder = ayon_api.get_folder_by_path(
                project["name"], folder_path.parents[0].as_posix()
            )
            episode_url = Path(
                gazu.shot.get_episode_url(
                    {
                        "project_id": project_kitsu_id,
                        "id": episode_folder["data"].get("kitsuId"),
                    }
                )
            )
            return f"{episode_url.parent}/sequences/{kitsu_id}"
        else:
            project_url = Path(
                gazu.project.get_project_url({"id": project_kitsu_id})
            )
            return f"{project_url.parent}/sequences/{kitsu_id}"

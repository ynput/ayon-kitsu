import webbrowser
import ayon_api

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

        project_zou_id = project["data"].get("zou_id")
        if not project_zou_id:
            raise RuntimeError(
                f"Project {project_name} has no connected kitsu id."
            )

        folder_kitsu_id = None
        folder_type = None
        task_kitsu_id = None
        if selection.is_folder_selected:
            folder_entity = selection.folder_entity
            folder_kitsu_id = folder_entity["data"].get("kitsuId")
            folder_type = folder_entity["folderType"]

            if selection.is_task_selected:
                task_entity = selection.task_entity
                task_kitsu_id = task_entity["data"].get("kitsuId")

        # Define URL
        url = self.get_url(
            project_zou_id,
            folder_kitsu_id,
            folder_type,
            task_kitsu_id,
        )

        # Open URL in webbrowser
        self.log.info(f"Opening URL: {url}")
        webbrowser.open(
            url,
            # Try in new tab
            new=2,
        )

    def get_url(
        self,
        project_kitsu_id,
        folder_kitsu_id=None,
        folder_type=None,
        task_id=None,
    ):
        shots_url = {"Shots", "Sequence", "Shot"}
        kitsu_addon = self.get_kitsu_addon()

        # Get kitsu url with /api stripped
        kitsu_url = kitsu_addon.server_url.rstrip("/api")

        sub_url = f"/productions/{project_kitsu_id}"
        kitsu_type = "shots" if folder_type in shots_url else "assets"

        if task_id:
            # Go to task page
            # /productions/{project-id}/{asset_type}/tasks/{task_id}
            sub_url += f"/{kitsu_type}/tasks/{task_id}"

        elif folder_kitsu_id:
            # Go to asset or shot page
            # /productions/{project-id}/assets/{entity_id}
            # /productions/{project-id}/shots/{entity_id}
            sub_url += f"/{kitsu_type}/{folder_kitsu_id}"

        return f"{kitsu_url}{sub_url}"

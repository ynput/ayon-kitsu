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

        project_zou_id = project["data"].get("kitsuProjectId")
        if not project_zou_id:
            raise RuntimeError(
                f"Project {project_name} has no connected kitsu id."
            )

        folder_kitsu_id = None
        task_kitsu_id = None
        if selection.is_folder_selected:
            folder_entity = selection.folder_entity
            folder_kitsu_id = folder_entity["data"].get("kitsuId")

            if selection.is_task_selected:
                task_entity = selection.task_entity
                task_kitsu_id = task_entity["data"].get("kitsuId")

        # Define URL
        url = self.get_url(
            project_zou_id,
            folder_kitsu_id,
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
        task_id=None,
    ):
        kitsu_addon = self.get_kitsu_addon()

        # Get kitsu url without /api
        kitsu_url = kitsu_addon.server_url
        if kitsu_url.endswith("/api"):
            kitsu_url = kitsu_url[:-4]

        url = f"{kitsu_url}/productions/{project_kitsu_id}"

        # Handle task first if available
        if task_id:
            # Go to task page
            task = gazu.task.get_task(task_id)
            if task:
                return f"{url}/{task['type']}s/tasks/{task_id}"

        # Handle folder entities
        if folder_kitsu_id:
            # Short IDs are typically for home page (assets, shots, etc.)
            if len(folder_kitsu_id) < 30:
                return f"{url}/{folder_kitsu_id}s"

            # Try to get the entity to determine its type
            try:
                entity = gazu.entity.get_entity(folder_kitsu_id)
            except gazu.exception.RouteNotFoundException:
                entity = None

            if entity:
                entity_type = entity.get("type", "").lower()
                if entity_type:
                    return f"{url}/{entity_type}s/{folder_kitsu_id}"
            else:
                pass
                # If not an entity, we assume it is a asset subtype e.g Props
                # So open the assets page
                return f"{url}/assets"

        # Default to project shots page
        return f"{url}/shots"

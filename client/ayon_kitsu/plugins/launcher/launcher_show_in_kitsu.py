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

    def process(self, session, **kwargs):
        # Context inputs
        project_name = session["AYON_PROJECT_NAME"]
        folder_path = session.get("AYON_FOLDER_PATH", None)
        task_name = session.get("AYON_TASK_NAME", None)

        project = ayon_api.get_project(project_name)
        if not project:
            raise RuntimeError("Project {} not found.".format(project_name))

        project_kitsu_id = project["data"].get("kitsuProjectId")
        if not project_kitsu_id:
            raise RuntimeError(
                "Project {} has no connected kitsu id.".format(project_name)
            )

        folder_name = None
        folder_kitsu_id = None
        folder_type = None
        task_kitsu_id = None

        if asset_path:
            folder_data = ayon_api.get_folder_by_path(project_name = project_name, folder_path = asset_path)
            folder_type = folder_data['folderType']
            folder_name = folder_path.split("/")[-1]
            folder_id = folder_data['id']
            folder_kitsu_id = folder_data['data']['kitsuId']
            if task_name:
                project_tasks = ayon_api.get_tasks(project_name = project_name)
                folder_tasks = [x for x in project_tasks if x['folderId'] == folder_id]
                folder_task = None
                for task in folder_tasks:
                    if task['name'] == task_name:
                        folder_task = task
                        break
                task_kitsu_id = folder_task['data']['kitsuId']

        url = self.get_url(
            project_id=project_kitsu_id,
            asset_name=folder_name,
            asset_id=folder_kitsu_id,
            asset_type=folder_type,
            task_id=task_kitsu_id,
        )

        # Open URL in webbrowser
        self.log.info("Opening URL: {}".format(url))
        webbrowser.open(
            url,
            # Try in new tab
            new=2,
        )

    def get_url(
        self,
        project_id,
        asset_name=None,
        asset_id=None,
        asset_type=None,
        task_id=None,
    ):
        kitsu_addon = self.get_kitsu_addon()

        # Get kitsu url with /api stripped
        kitsu_url = kitsu_addon.server_url.rstrip("/api")

        sub_url = f"/productions/{project_id}"
        asset_type_url = "sequences" if asset_type == "Sequence" or asset_name == "Sequences" else "shots" if asset_type == "Shot" else "assets"

        if task_id:
            # Go to task page
            # /productions/{project-id}/{asset_type}/tasks/{task_id}
            sub_url += f"/{asset_type_url}/tasks/{task_id}"

        elif asset_id and asset_type != "Folder" and asset_type_url != "sequences":
            # Go to asset or shot page
            # /productions/{project-id}/assets/{entity_id}
            # /productions/{project-id}/shots/{entity_id}
            sub_url += f"/{asset_type_url}/{asset_id}"

        else:
            # Go to project page
            # Project page must end with a view
            # /productions/{project-id}/assets/
            # Add search method if is a sub_type
            sub_url += f"/{asset_type_url}"
            sub_url += f"?search={asset_name}" if asset_name not in [None, "Assets", "Sequences"] else "?search="

        return f"{kitsu_url}{sub_url}"

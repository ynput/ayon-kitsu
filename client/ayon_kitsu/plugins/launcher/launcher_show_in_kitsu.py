try:
    from openpype.pipeline import LauncherAction
    from openpype.modules import ModulesManager

except ImportError:
    from ayon_core.pipeline import LauncherAction
    from ayon_core.modules import ModulesManager

import webbrowser
import ayon_api
import re


class ShowInKitsu(LauncherAction):
    name = "showinkitsu"
    label = "Show in Kitsu"
    icon = "external-link-square"
    # color = "#e0e1e1"
    order = 10

    @staticmethod
    def get_kitsu_module():
        return ModulesManager().modules_by_name.get("kitsu")

    def is_compatible(self, session):
        """Return whether the action is compatible with the session"""
        return bool(self.get_kitsu_data(session))

    def get_kitsu_data(self, session):
        ## example session
        # {'AVALON_PROJECT': 'Test_Project', 'AVALON_ASSET': '/episodes/test_ep/010/001', 'AVALON_TASK': 'mytask'}

        # support for ayon_core
        project_name = session.get("AYON_PROJECT_NAME", None)
        folder_path = session.get("AYON_FOLDER_PATH", None)
        task_name = session.get("AYON_TASK_NAME", None)

        # support for OpenPype
        if not project_name:
            project_name = session.get("AVALON_PROJECT", None)
            folder_path = session.get("AVALON_ASSET", None)
            task_name = session.get("AVALON_TASK", None)

        if not project_name or not folder_path:
            return

        project = ayon_api.get_project(project_name)
        if not project:
            return

        data = project.get("data")
        kitsu_project_id = data.get("kitsuProjectId") if data else None

        if not kitsu_project_id:
            return None

        kitsu_entity_id = None
        kitsu_entity_type = None
        kitsu_task_id = None

        folder = ayon_api.get_folder_by_path(project_name, folder_path)
        if not folder:
            return
        data = folder.get("data")
        kitsu_entity_id = data.get("kitsuId") if data else None
        kitsu_entity_type = data.get("kitsuType") if data else None

        # required data
        if not kitsu_entity_id or not kitsu_entity_type:
            return

        if task_name:
            task = ayon_api.get_task_by_name(project_name, folder.get("id"), task_name)
            if not task:
                return
            data = task.get("data")
            kitsu_task_id = data.get("kitsuId") if data else None

        # print(f"kitsu_project_id: {kitsu_project_id}")
        # print(f"kitsu_entity_type: {kitsu_entity_type}")
        # print(f"kitsu_entity_id: {kitsu_entity_id}")
        # print(f"kitsu_task_id: {kitsu_task_id}")

        return (kitsu_project_id, kitsu_entity_type, kitsu_entity_id, kitsu_task_id)

    def process(self, session, **kwargs):
        result = self.get_kitsu_data(session)
        if not result:
            return

        kitsu_project_id, kitsu_entity_type, kitsu_entity_id, kitsu_task_id = result

        # # Define URL
        url = self.get_url(
            project_id=kitsu_project_id,
            entity_id=kitsu_entity_id,
            entity_type=kitsu_entity_type,
            task_id=kitsu_task_id,
        )
        if not url:
            raise Exception("URL cound not be created")

        # # Open URL in webbrowser
        self.log.info(f"Opening URL: {url}")
        webbrowser.open(
            url,
            # Try in new tab
            new=2,
        )

    def get_url(
        self,
        project_id,
        entity_id=None,
        entity_type=None,
        task_id=None,
    ):
        # sub_type = {"AssetType", "Sequence"}
        kitsu_module = self.get_kitsu_module()

        # Get kitsu url with /api stripped
        kitsu_url = kitsu_module.server_url
        kitsu_url = re.sub(r"\/?(api)?\/?$", "", kitsu_url)

        sub_url = f"/productions/{project_id}"
        type_url = f"{entity_type.lower()}s" if entity_type else "shots"

        if task_id:
            # Go to task page
            # /productions/{project-id}/{type}/tasks/{task_id}
            sub_url += f"/{type_url}/tasks/{task_id}"

        elif entity_id:
            # Go to asset or shot page
            # /productions/{project-id}/assets/{entity_id}
            # /productions/{project-id}/shots/{entity_id}
            sub_url += f"/{type_url}/{entity_id}"

        # else:
        #     # Go to project page
        #     # Project page must end with a view
        #     # /productions/{project-id}/assets/
        #     # Add search method if is a sub_type
        #     sub_url += f"/{asset_type_url}"
        #     if asset_type in sub_type:
        #         sub_url += f"?search={asset_name}"

        return f"{kitsu_url}{sub_url}"

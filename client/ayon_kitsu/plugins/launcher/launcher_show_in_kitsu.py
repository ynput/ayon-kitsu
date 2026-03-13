from pathlib import Path
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

        # Define URL
        url = self.get_url(
            project,
            selection.folder_entity if selection.is_folder_selected else None,
            selection.task_entity if selection.is_task_selected else None,
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
        project,
        folder=None,
        task=None,
    ):
        if not (project_kitsu_id := project["data"].get("kitsuProjectId")):
            raise RuntimeError(
                f"Project {project['name']} has no connected kitsu id."
            )

        if task:
            return gazu.task.get_task_url(
                {"project_id": project_kitsu_id, "id": task.get("kitsuId")}
            )
        elif folder:
            project_url = Path(
                gazu.project.get_project_url({"id": project_kitsu_id})
            )
            folder_type = folder["folderType"]
            folder_path = Path(folder["path"])
            kitsu_id = folder["data"].get("kitsuId")
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

    def _get_asset_type_url(self, project_kitsu_id, folder_label):
        """Get the URL for the asset type page.

        Meant to be replaced by gazu.asset.get_asset_type_url when available.
        See https://github.com/cgwire/gazu/issues/392
        """
        project_url = Path(
            gazu.project.get_project_url({"id": project_kitsu_id})
        )
        return (
            f"{project_url.parent}/episodes/all/assets",
            f"?search=+type=[{folder_label}]",
        )

    def _get_sequence_url(
        self, project, project_kitsu_id, kitsu_id, folder_path
    ):
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

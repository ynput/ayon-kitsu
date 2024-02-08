import re

import ayon_api
import gazu
from ayon_api.entity_hub import EntityHub
from nxtools import log_traceback, logging

from kitsu_common.utils import (
    KitsuServerError,
    create_kitsu_entities_in_ay,
)

PROJECT_NAME_REGEX = re.compile("^[a-zA-Z0-9_]+$")


class AyonKitsuHub:
    """A Hub to manage a Project in both AYON and Kitsu

    Provided a correct project name and code, we attempt to initialize both APIs
    and ensures that both platforms have the required elements to syncronize a
    project across them.

    The Kitsu credentials must have enough permissions to add fields to
    entities and create entities/projects.

    Args:
        project_name (str):The project name, cannot contain spaces.
        project_code (str): The project code (3 letter code).
        kitsu_server_url (str): The URL of the Kitsu instance.
        kitsu_login_email (str): An email adress to access all Kitsu data.
        kitsu_login_password (str): The password to access all Kitsu data.
    """

    def __init__(
        self,
        project_name: str,
        project_code: str,
        kitsu_server_url: str,
        kitsu_login_email: str,
        kitsu_login_password: str,
    ):
        if not all([kitsu_server_url, kitsu_login_email, kitsu_login_password]):
            msg = (
                "AyonKitsuHub requires `kitsu_server_url`, `kitsu_login_email`"
                "and `kitsu_login_password` as arguments."
            )
            logging.error(msg)
            raise ValueError(msg)

        self._initialize_apis(kitsu_server_url, kitsu_login_email, kitsu_login_password)

        self._ay_project = None
        self._kitsu_project = None

        self.project_name = project_name
        self.project_code = project_code

    def _initialize_apis(
        self, kitsu_server_url: str, kitsu_login_email: str, kitsu_login_password: str
    ):
        """Ensure we can talk to AYON and Kitsu.

        Start connections to the APIs and catch any possible error, we abort if
        this steps fails for any reason.
        """
        try:
            ayon_api.init_service()
        except Exception as e:
            logging.error("Unable to connect to AYON.")
            log_traceback(e)
            raise (e)

        gazu.set_host(kitsu_server_url)
        if not gazu.client.host_is_valid():
            msg = f"Kitsu server `{kitsu_server_url}` is not valid"
            logging.error(msg)
            log_traceback(msg)
            raise KitsuServerError(msg)

        try:
            gazu.log_in(kitsu_login_email, kitsu_login_password)
        except gazu.exception.AuthFailedException as e:
            msg = f"Kitsu login failed: {e}"
            logging.error(msg)
            log_traceback(msg)
            raise KitsuServerError(msg) from e

    def _check_for_missing_sg_attributes(self):
        """Check if Kitsu has all the fields.

        In order to sync to work, Kitsu needs to have certain fields in both
        the Project and the entities within it, if any is missing this will raise.
        """
        # TODO
        pass

    def create_kitsu_attributes(self):
        """Create all AYON needed attributes in Kitsu."""
        # create_ay_fields_in_kitsu_project()
        # create_ay_fields_in_kitsu_entities()
        # TODO
        pass

    @property
    def project_name(self) -> str:
        return self._project_name

    @project_name.setter
    def project_name(self, project_name: str):
        """Set the project name

        We make sure the name follows the conventions imposed by ayon-backend,
        and if it passes we attempt to find the project in both platfomrs.
        """
        if not PROJECT_NAME_REGEX.match(project_name):
            raise ValueError(f"Invalid Project Name: {project_name}")

        self._project_name = project_name

        try:
            self._ay_project = EntityHub(project_name)
            self._ay_project.project_entity
            logging.info(
                f"Project {project_name} <{self._ay_project.project_entity.id}> already exists in AYON."
            )
        except Exception as err:
            logging.warning(f"Project {project_name} does not exist in AYON.")
            log_traceback(err)
            self._ay_project = None

        try:
            self._kitsu_project = gazu.project.get_project_by_name(self.project_name)
            logging.info(
                f"Project {project_name} <{self._kitsu_project['id']}> already exists in Kitsu."
            )
        except Exception as e:
            logging.warning(f"Project {project_name} does not exist in Kitsu.")
            log_traceback(e)
            self._kitsu_project = None

    def create_project(self, kitsu_event: dict[str, str]):
        """Create project in AYON and Kitsu.

        This step is also where we create all the required fields in Kitsu
        entities.
        """
        if self._ay_project is None:
            logging.info(
                f"Creating AYON project {self.project_name} ({self.project_code})."
            )
            ayon_api.create_project(self.project_name, self.project_code)
            self._ay_project = EntityHub(self.project_name)
            self._ay_project.query_entities_from_server()
        else:
            logging.info(
                f"Project {self.project_name} ({self.project_code}) already exists in AYON."
            )

        # self.create_kitsu_attributes()
        self._ay_project.commit_changes()

        # TODO Add Ayon to Kitsu code
        """
        if self._kitsu_project is None:
            logging.info(
                f"Creating Kitsu project {self.project_name} ({self.project_code})."
            )
            self._kitsu_project = gazu.project.new_project(
                name="name",
                production_type="short",
                team=[],
                asset_types=[],
                task_statuses=[],
                task_types=[],
                production_style="2d3d",
            )
            self._ay_project.project_entity.attribs.set(
                "kitsuId", self._kitsu_project["id"]
            )

            self._ay_project.project_entity.attribs.set(SHOTGRID_TYPE_ATTRIB, "Project")
            self._ay_project.commit_changes()
        else:
            logging.info(
                f"Project {self.project_name} ({self.project_code}) already exists in Kitsu."
            )
        """

    def syncronize_project(self, source: str = "ayon"):
        """Ensure a Project matches in the other platform.

        Args:
            source (str): Either "ayon" or "kitsu", dictates which one is the
                "source of truth".
        """
        if not self._ay_project or not self._kitsu_project:
            raise ValueError(
                """The project is missing in one of the two platforms:
                AYON: {0}
                Kitsu:{1}""".format(
                    self._ay_project, self._kitsu_project
                )
            )

        match source:
            case "ayon":
                """
                disabled_entities = []
                ay_entities = [
                    folder["name"]
                    for folder in self._ay_project.project_entity.folder_types
                    if folder["name"] in AYON_SHOTGRID_ENTITY_TYPE_MAP.keys()
                ]

                sg_entities = [
                    entity_name
                    for entity_name, _ in get_sg_project_enabled_entities(
                        self._sg, self._sg_project
                    )
                ]

                disabled_entities = [
                    ay_entity
                    for ay_entity in ay_entities
                    if ay_entity not in sg_entities
                ]

                if disabled_entities:
                    raise ValueError(
                        f"Unable to sync project {self.project_name} "
                        f"<{self.project_code}> from AYON to Shotgrid, you need "
                        "to enable the following entities in the Shotgrid Project "
                        f"> Project Actions > Tracking Settings: {disabled_entities}"
                    )

                match_ayon_hierarchy_in_shotgrid(
                    self._ay_project,
                    self._sg_project,
                    self._sg,
                    self.sg_project_code_field,
                )
                """

            case "kitsu":
                create_kitsu_entities_in_ay(
                    self._ay_project.project_entity,
                    self._kitsu_project,
                )
                self._ay_project.commit_changes()

                # match_shotgrid_hierarchy_in_ayon(
                #    self._ay_project,
                #    self._sg_project,
                #    self._sg,
                #    self.sg_project_code_field,
                # )

            case _:
                raise ValueError(
                    f"The `source` argument can only be `ayon` or `kitsu`, got '{source}'"
                )

    def react_to_kitsu_event(self, kitsu_event: dict[str, str]):
        """React to events incoming from Kitsu

        Whenever there's a `kitsu.event` spawned by the `leecher` of a change
        in Kitsu, we pass said event.

        The current scope of what changes and what attributes we care is limited,
        this is to be expanded.

        Args:
            kitsu_event (dict): The `meta` key of a Shogrid Event, describing what
                the change encompases, i.e. a new shot, new asset, etc.
        """

        match kitsu_event["event_type"]:
            case "task:new":
                create_ay_entity_from_kitsu_event(
                    kitsu_event,
                    self._kitsu_project,
                    self._ay_project,
                )
            case _:
                msg = f"Unable to process event {kitsu_event['type']}."
                logging.error(msg)
                raise ValueError(msg)

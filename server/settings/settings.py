from pydantic import Field

from ayon_server.settings import BaseSettingsModel
from ayon_server.settings.enum import secrets_enum
from ayon_server.types import NAME_REGEX


#
## Entities naming pattern
#
class EntityPattern(BaseSettingsModel):
    episode: str = Field(title="Episode")
    sequence: str = Field(title="Sequence")
    shot: str = Field(title="Shot")


#
## Publish plugins
#
def _status_change_cond_enum():
    return [
        {"value": "equal", "label": "Equal"},
        {"value": "not_equal", "label": "Not equal"},
    ]


class StatusChangeCondition(BaseSettingsModel):
    condition: str = Field(
        "equal", enum_resolver=_status_change_cond_enum, title="Condition"
    )
    short_name: str = Field("", title="Short name")


class StatusChangeProductTypeRequirementModel(BaseSettingsModel):
    condition: str = Field(
        "equal", enum_resolver=_status_change_cond_enum, title="Condition"
    )
    product_type: str = Field("", title="Product type")


class StatusChangeConditionsModel(BaseSettingsModel):
    status_conditions: list[StatusChangeCondition] = Field(
        default_factory=list, title="Status conditions"
    )
    product_type_requirements: list[StatusChangeProductTypeRequirementModel] = Field(
        default_factory=list, title="Product type requirements"
    )


class CustomCommentTemplateModel(BaseSettingsModel):
    """Kitsu supports markdown and here you can create a custom comment template.

    You can use data from your publishing instance's data.
    """

    enabled: bool = Field(True)
    comment_template: str = Field("", title="Custom comment")


class IntegrateKitsuNotes(BaseSettingsModel):
    set_status_note: bool = Field(title="Set status on note")
    note_status_shortname: str = Field(title="Note shortname")
    status_change_conditions: StatusChangeConditionsModel = Field(
        default_factory=StatusChangeConditionsModel, title="Status change conditions"
    )
    custom_comment_template: CustomCommentTemplateModel = Field(
        default_factory=CustomCommentTemplateModel,
        title="Custom Comment Template",
    )


class PublishPlugins(BaseSettingsModel):
    IntegrateKitsuNote: IntegrateKitsuNotes = Field(
        default_factory=IntegrateKitsuNotes, title="Integrate Kitsu Note"
    )


#
## Sync users
#
def _roles_enum():
    return [
        {"value": "user", "label": "User"},
        {"value": "manager", "label": "Manager"},
        {"value": "admin", "label": "Admin"},
    ]


class RolesCondition(BaseSettingsModel):
    """Set what Ayon role users should get based in their Kitsu role"""

    admin: str = Field("admin", enum_resolver=_roles_enum, title="Studio manager")
    vendor: str = Field("user", enum_resolver=_roles_enum, title="Vendor")
    client: str = Field("user", enum_resolver=_roles_enum, title="Client")
    manager: str = Field(
        "manager", enum_resolver=_roles_enum, title="Production manager"
    )
    supervisor: str = Field("manager", enum_resolver=_roles_enum, title="Supervisor")
    user: str = Field("user", enum_resolver=_roles_enum, title="Artist")


class SyncUsers(BaseSettingsModel):
    """When a Kitsu user is synced, the default password will be set for the newly created user.
    Please ask the user to change the password inside Ayon.
    """

    enabled: bool = Field(True)
    default_password: str = Field(title="Default Password")
    access_group: str = Field(title="Access Group", regex=NAME_REGEX)
    roles: RolesCondition = Field(default_factory=RolesCondition, title="Roles")


#
## Default task info
#
def _states_enum():
    return [
        {"value": "not_started", "label": "Not started"},
        {"value": "in_progress", "label": "In progress"},
        {"value": "done", "label": "Done"},
        {"value": "blocked", "label": "Blocked"},
    ]


class TaskCondition(BaseSettingsModel):
    _layout: str = "compact"
    name: str = Field("", title="Name")
    short_name: str = Field("", title="Short name")
    icon: str = Field("task_alt", title="Icon", widget="icon")


class StatusCondition(BaseSettingsModel):
    _layout: str = "compact"
    short_name: str = Field("", title="Short name")
    state: str = Field("in_progress", enum_resolver=_states_enum, title="State")
    icon: str = Field("task_alt", title="Icon", widget="icon")


class DefaultSyncInfo(BaseSettingsModel):
    """As statuses already have names and short names we only need the short name to match Kitsu with Ayon"""

    default_task_info: list[TaskCondition] = Field(default_factory=list, title="Tasks")
    default_status_info: list[StatusCondition] = Field(
        default_factory=list, title="Statuses"
    )


#
## Sync settings
#
class SyncSettings(BaseSettingsModel):
    """Enabling 'Delete projects' will remove projects on Ayon when they get deleted on Kitsu"""

    delete_projects: bool = Field(title="Delete projects")
    sync_users: SyncUsers = Field(
        default_factory=SyncUsers,
        title="Sync users",
    )
    default_sync_info: DefaultSyncInfo = Field(
        default_factory=DefaultSyncInfo,
        title="Default sync info",
    )


class KitsuSettings(BaseSettingsModel):
    #
    ## Root fields
    #
    server: str = Field(
        "",
        title="Kitsu Server",
        scope=["studio"],
    )
    login_email: str = Field(
        "kitsu_email",
        enum_resolver=secrets_enum,
        title="Kitsu user email",
        scope=["studio"],
    )
    login_password: str | None = Field(
        "kitsu_password",
        enum_resolver=secrets_enum,
        title="Kitsu user password",
        scope=["studio"],
    )

    #
    ## Sub entities
    #
    entities_naming_pattern: EntityPattern = Field(
        default_factory=EntityPattern,
        title="Entities naming pattern",
    )
    publish: PublishPlugins = Field(
        default_factory=PublishPlugins,
        title="Publish plugins",
    )
    sync_settings: SyncSettings = Field(
        default_factory=SyncSettings,
        title="Sync settings",
    )

from ayon_server.settings import BaseSettingsModel, SettingsField
from ayon_server.settings.enum import secrets_enum
from ayon_server.types import NAME_REGEX


#
## Entities naming pattern
#
class EntityPattern(BaseSettingsModel):
    episode: str = SettingsField(title="Episode")
    sequence: str = SettingsField(title="Sequence")
    shot: str = SettingsField(title="Shot")


#
## Publish plugins
#
def _status_change_cond_enum():
    return [
        {"value": "equal", "label": "Equal"},
        {"value": "not_equal", "label": "Not equal"},
    ]


class StatusChangeCondition(BaseSettingsModel):
    condition: str = SettingsField(
        "equal", enum_resolver=_status_change_cond_enum, title="Condition"
    )
    short_name: str = SettingsField("", title="Short name")


class StatusChangeFamilyRequirementModel(BaseSettingsModel):
    condition: str = SettingsField(
        "equal", enum_resolver=_status_change_cond_enum, title="Condition"
    )
    product_type: str = SettingsField("", title="Family")


class StatusChangeConditionsModel(BaseSettingsModel):
    status_conditions: list[StatusChangeCondition] = SettingsField(
        default_factory=list, title="Status conditions"
    )
    family_requirements: list[StatusChangeFamilyRequirementModel] = SettingsField(
        default_factory=list, title="Family requirements"
    )


class CustomCommentTemplateModel(BaseSettingsModel):
    """Kitsu supports markdown and here you can create a custom comment template.

    You can use data from your publishing instance's data.
    """

    enabled: bool = SettingsField(True)
    comment_template: str = SettingsField("", widget="textarea", title="Custom comment")


class IntegrateKitsuNotes(BaseSettingsModel):
    set_status_note: bool = SettingsField(title="Set status on note")
    note_status_shortname: str = SettingsField(title="Note shortname")
    status_change_conditions: StatusChangeConditionsModel = SettingsField(
        default_factory=StatusChangeConditionsModel, title="Status change conditions"
    )
    custom_comment_template: CustomCommentTemplateModel = SettingsField(
        default_factory=CustomCommentTemplateModel,
        title="Custom Comment Template",
    )


class PublishPlugins(BaseSettingsModel):
    IntegrateKitsuNote: IntegrateKitsuNotes = SettingsField(
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

    admin: str = SettingsField(
        "admin", enum_resolver=_roles_enum, title="Studio manager"
    )
    vendor: str = SettingsField(
        "user", enum_resolver=_roles_enum, title="Vendor"
    )
    client: str = SettingsField(
        "user", enum_resolver=_roles_enum, title="Client"
    )
    manager: str = SettingsField(
        "manager", enum_resolver=_roles_enum, title="Production manager"
    )
    supervisor: str = SettingsField(
        "manager", enum_resolver=_roles_enum, title="Supervisor"
    )
    user: str = SettingsField(
        "user", enum_resolver=_roles_enum, title="Artist"
    )


class SyncUsers(BaseSettingsModel):
    """When a Kitsu user is synced, the default password will be set for the newly created user.
    Please ask the user to change the password inside Ayon.
    """

    enabled: bool = SettingsField(True)
    default_password: str = SettingsField(title="Default Password")
    access_group: str = SettingsField(title="Access Group", regex=NAME_REGEX)
    roles: RolesCondition = SettingsField(default_factory=RolesCondition, title="Roles")


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
    name: str = SettingsField("", title="Name")
    short_name: str = SettingsField("", title="Short name")
    icon: str = SettingsField("task_alt", title="Icon", widget="icon")


class StatusCondition(BaseSettingsModel):
    _layout: str = "compact"
    short_name: str = SettingsField("", title="Short name")
    state: str = SettingsField("in_progress", enum_resolver=_states_enum, title="State")
    icon: str = SettingsField("task_alt", title="Icon", widget="icon")


class DefaultSyncInfo(BaseSettingsModel):
    """As statuses already have names and short names we only need the short name to match Kitsu with Ayon"""

    default_task_info: list[TaskCondition] = SettingsField(
        default_factory=list, title="Tasks"
    )
    default_status_info: list[StatusCondition] = SettingsField(
        default_factory=list, title="Statuses"
    )


#
## Sync settings
#
class SyncSettings(BaseSettingsModel):
    """Enabling 'Delete projects' will remove projects on Ayon when they get deleted on Kitsu"""

    delete_projects: bool = SettingsField(title="Delete projects")
    sync_users: SyncUsers = SettingsField(
        default_factory=SyncUsers,
        title="Sync users",
    )
    default_sync_info: DefaultSyncInfo = SettingsField(
        default_factory=DefaultSyncInfo,
        title="Default sync info",
    )


class KitsuSettings(BaseSettingsModel):
    #
    ## Root fields
    #
    enabled: bool = SettingsField(True, title="Enabled")
    server: str = SettingsField(
        "",
        title="Kitsu Server",
        scope=["studio"],
    )
    login_email: str = SettingsField(
        "kitsu_email",
        enum_resolver=secrets_enum,
        title="Kitsu user email",
        scope=["studio"],
    )
    login_password: str | None = SettingsField(
        "kitsu_password",
        enum_resolver=secrets_enum,
        title="Kitsu user password",
        scope=["studio"],
    )

    #
    ## Sub entities
    #
    entities_naming_pattern: EntityPattern = SettingsField(
        default_factory=EntityPattern,
        title="Entities naming pattern",
    )
    publish: PublishPlugins = SettingsField(
        default_factory=PublishPlugins,
        title="Publish plugins",
    )
    sync_settings: SyncSettings = SettingsField(
        default_factory=SyncSettings,
        title="Sync settings",
    )

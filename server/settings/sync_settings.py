from ayon_server.settings import BaseSettingsModel, SettingsField
from ayon_server.types import NAME_REGEX


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
    """When a Kitsu user is synced, the default password will be set for
    the newly created user. Please ask the user to change the password
    inside Ayon.
    """

    enabled: bool = SettingsField(True)
    default_password: str = SettingsField(title="Default Password")
    access_group: str = SettingsField(
        title="Access Group",
        description=(
            "AYON access group given to synced users. It is created when it"
            " does not exist yet."
        ),
        regex=NAME_REGEX,
    )
    roles: RolesCondition = SettingsField(
        default_factory=RolesCondition, title="Roles"
    )


#
## Default task info
#
class TaskCondition(BaseSettingsModel):
    _layout: str = "compact"
    name: str = SettingsField("", title="Name")
    short_name: str = SettingsField("", title="Short name")
    icon: str = SettingsField("task_alt", title="Icon", widget="icon")


def _states_enum():
    return [
        {"value": "not_started", "label": "Not started"},
        {"value": "in_progress", "label": "In progress"},
        {"value": "done", "label": "Done"},
        {"value": "blocked", "label": "Blocked"},
    ]


class StatusCondition(BaseSettingsModel):
    _layout: str = "compact"
    short_name: str = SettingsField("", title="Short name")
    state: str = SettingsField(
        "in_progress", enum_resolver=_states_enum, title="State"
    )
    icon: str = SettingsField("task_alt", title="Icon", widget="icon")


class DefaultSyncInfo(BaseSettingsModel):
    """As statuses already have names and short names we only need the short
    name to match Kitsu with Ayon.
    """

    default_task_info: list[TaskCondition] = SettingsField(
        default_factory=list, title="Tasks"
    )
    default_status_info: list[StatusCondition] = SettingsField(
        default_factory=list, title="Statuses"
    )


class SyncCasting(BaseSettingsModel):
    enabled: bool = SettingsField(
        False,
        title="Sync casting links",
        description=(
            "Create AYON links between a shot or asset and the assets cast"
            " on it in the Kitsu breakdown."
        ),
    )
    casting_link_type: str = SettingsField(
        "breakdown",
        title="Casting link type",
        description=(
            "Name of the AYON link type used for casting links. It is"
            " expanded to 'name|folder|folder', as casting always links a"
            " folder to a folder."
        ),
        regex=NAME_REGEX,
    )


#
## Two-way sync (experimental AYON to Kitsu sync)
#
def _conflict_policy_enum():
    """Return the conflict policies offered for two-way sync.

    Returns:
        list[dict[str, str]]: Enum items with ``value`` and ``label`` keys.
    """
    return [
        {"value": "kitsu_wins", "label": "Kitsu wins"},
        {"value": "ayon_wins", "label": "AYON wins"},
    ]


class TwoWaySyncSettings(BaseSettingsModel):
    """Experimental AYON to Kitsu sync. Every toggle is off by default.

    Nothing is written to Kitsu unless the master toggle and the toggle of
    the change's category are both enabled. Project overrides take
    precedence over studio values.
    """

    enabled: bool = SettingsField(
        False,
        title="Enable AYON to Kitsu sync",
        description=(
            "Master toggle. When disabled, no AYON change is written to"
            " Kitsu, whatever the category toggles are."
        ),
    )
    task_status: bool = SettingsField(False, title="Task status")
    task_assignees: bool = SettingsField(False, title="Task assignees")
    entity_attributes: bool = SettingsField(
        False,
        title="Entity attributes",
        description="Frame range, fps, resolution and description.",
    )
    entity_creation: bool = SettingsField(False, title="Entity creation")
    entity_rename: bool = SettingsField(False, title="Entity rename")
    entity_deletion: bool = SettingsField(False, title="Entity deletion")
    conflict_policy: str = SettingsField(
        "kitsu_wins",
        enum_resolver=_conflict_policy_enum,
        title="Conflict policy",
        description=(
            "What happens when the Kitsu value changed since the AYON value"
            " was last synced. 'Kitsu wins' keeps the Kitsu value and syncs"
            " it back to AYON. 'AYON wins' overwrites Kitsu."
        ),
    )


class SyncSettings(BaseSettingsModel):
    """Enabling 'Delete projects' will remove projects on Ayon when they get
    deleted on Kitsu.
    """

    delete_projects: bool = SettingsField(title="Delete projects")
    sync_users: SyncUsers = SettingsField(
        default_factory=SyncUsers,
        title="Sync users",
    )
    sync_casting: SyncCasting = SettingsField(
        default_factory=SyncCasting,
        title="Sync casting",
    )
    two_way_sync: TwoWaySyncSettings = SettingsField(
        default_factory=TwoWaySyncSettings,
        title="Two-way sync (experimental)",
    )
    default_sync_info: DefaultSyncInfo = SettingsField(
        default_factory=DefaultSyncInfo,
        title="Default sync info",
    )


SYNC_DEFAULT_VALUES = {
    "delete_projects": False,
    "sync_users": {
        "enabled": False,
        "default_password": "default_password",
        "access_group": "kitsu_group",
    },
    "sync_casting": {
        "enabled": False,
        "casting_link_type": "breakdown",
    },
    "two_way_sync": {
        "enabled": False,
        "task_status": False,
        "task_assignees": False,
        "entity_attributes": False,
        "entity_creation": False,
        "entity_rename": False,
        "entity_deletion": False,
        "conflict_policy": "kitsu_wins",
    },
    "default_sync_info": {
        "default_task_info": [
            {
                "name": "Concept",
                "short_name": "cncp",
                "icon": "lightbulb",
            },
            {
                "name": "Modeling",
                "short_name": "mdl",
                "icon": "language",
            },
            {
                "name": "Shading",
                "short_name": "shdn",
                "icon": "format_paint",
            },
            {
                "name": "Rigging",
                "short_name": "rig",
                "icon": "construction",
            },
            {
                "name": "Edit",
                "short_name": "edit",
                "icon": "cut",
            },
            {
                "name": "Storyboard",
                "short_name": "stry",
                "icon": "image",
            },
            {
                "name": "Layout",
                "short_name": "lay",
                "icon": "nature_people",
            },
            {
                "name": "Animation",
                "short_name": "anim",
                "icon": "directions_run",
            },
            {
                "name": "Lighting",
                "short_name": "lgt",
                "icon": "highlight",
            },
            {
                "name": "FX",
                "short_name": "fx",
                "icon": "local_fire_department",
            },
            {
                "name": "Compositing",
                "short_name": "comp",
                "icon": "layers",
            },
            {
                "name": "Recording",
                "short_name": "rcrd",
                "icon": "video_camera_back",
            },
        ],
        "default_status_info": [
            {
                "short_name": "todo",
                "state": "not_started",
                "icon": "fiber_new",
            },
            {
                "short_name": "neutral",
                "state": "in_progress",
                "icon": "timer",
            },
            {
                "short_name": "wip",
                "state": "in_progress",
                "icon": "play_arrow",
            },
            {
                "short_name": "wfa",
                "state": "in_progress",
                "icon": "visibility",
            },
            {
                "short_name": "retake",
                "state": "in_progress",
                "icon": "timer",
            },
            {
                "short_name": "done",
                "state": "done",
                "icon": "task_alt",
            },
            {
                "short_name": "ready",
                "state": "not_started",
                "icon": "timer",
            },
            {
                "short_name": "approved",
                "state": "done",
                "icon": "task_alt",
            },
            {
                "short_name": "rejected",
                "state": "blocked",
                "icon": "block",
            },
        ],
    },
}

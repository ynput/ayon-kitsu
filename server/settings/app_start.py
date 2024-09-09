from ayon_server.settings import BaseSettingsModel, SettingsField


def _status_change_cond_enum():
    return [
        {"value": "equal", "label": "Equal"},
        {"value": "not_equal", "label": "Not equal"},
    ]


class AppStartStatusChangeCondition(BaseSettingsModel):
    condition: str = SettingsField(
        "equal", enum_resolver=_status_change_cond_enum, title="Condition"
    )
    short_name: str = SettingsField("", title="Short name")


class AppStartStatusChange(BaseSettingsModel):
    set_status_app_start_note: bool = SettingsField(title="Set status change on app start")
    app_start_status_shortname: str = SettingsField(title="App start Status shortname")
    app_startstatus_change_conditions: list[AppStartStatusChangeCondition] = SettingsField(
        default_factory=AppStartStatusChangeCondition, title="App start status change conditions"
    )
    set_pause_status_to_other_tasks: bool = SettingsField(title="Set pause status to other tasks")
    pause_status_shortname: str = SettingsField(title="Pause Status shortname")


APPSTART_DEFAULT_VALUES = {
    "set_status_app_start_note": False,
    "app_start_status_shortname": "wip",
    "app_startstatus_change_conditions": [],
    "set_pause_status_to_other_tasks": False,
    "pause_status_shortname": "pause",
    }

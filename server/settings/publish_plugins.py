from ayon_server.settings import BaseSettingsModel, SettingsField


class CollectFamilyAdvancedFilterModel(BaseSettingsModel):
    _layout = "expanded"
    families: list[str] = SettingsField(
        default_factory=list, title="Additional Families"
    )
    add_kitsu_family: bool = SettingsField(True, title="Add Kitsu Family")


class CollectFamilyProfile(BaseSettingsModel):
    _layout = "expanded"
    host_names: list[str] = SettingsField(
        default_factory=list,
        title="Host names",
    )
    product_types: list[str] = SettingsField(
        default_factory=list,
        title="Families",
    )
    task_types: list[str] = SettingsField(
        default_factory=list,
        title="Task types",
    )
    task_names: list[str] = SettingsField(
        default_factory=list,
        title="Task names",
    )
    add_kitsu_family: bool = SettingsField(
        True,
        title="Add Kitsu Family",
    )
    advanced_filtering: list[CollectFamilyAdvancedFilterModel] = SettingsField(
        title="Advanced adding if additional families present",
        default_factory=list,
    )


class CollectKitsuFamilyPluginModel(BaseSettingsModel):
    _isGroup = True
    enabled: bool = True
    profiles: list[CollectFamilyProfile] = SettingsField(
        default_factory=list,
        title="Profiles",
    )


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
    family_requirements: list[StatusChangeFamilyRequirementModel] = (
        SettingsField(default_factory=list, title="Family requirements")
    )


class CustomCommentTemplateModel(BaseSettingsModel):
    """Kitsu supports markdown and here you can create a custom comment template.

    You can use data from your publishing instance's data.
    """

    enabled: bool = SettingsField(True)
    comment_template: str = SettingsField(
        "", widget="textarea", title="Custom comment"
    )


class IntegrateKitsuNotes(BaseSettingsModel):
    set_status_note: bool = SettingsField(title="Set status on note")
    note_status_shortname: str = SettingsField(title="Note shortname")
    status_change_conditions: StatusChangeConditionsModel = SettingsField(
        default_factory=StatusChangeConditionsModel,
        title="Status change conditions",
    )
    custom_comment_template: CustomCommentTemplateModel = SettingsField(
        default_factory=CustomCommentTemplateModel,
        title="Custom Comment Template",
    )


class PublishPlugins(BaseSettingsModel):
    CollectKitsuFamily: CollectKitsuFamilyPluginModel = SettingsField(
        default_factory=CollectKitsuFamilyPluginModel,
        title="Collect Kitsu Family",
    )
    IntegrateKitsuNote: IntegrateKitsuNotes = SettingsField(
        default_factory=IntegrateKitsuNotes, title="Integrate Kitsu Note"
    )


PUBLISH_DEFAULT_VALUES = {
    "CollectKitsuFamily": {
        "enabled": True,
        "profiles": [
            {
                "host_names": ["traypublisher"],
                "product_types": [],
                "task_types": [],
                "task_names": [],
                "add_ftrack_family": True,
                "advanced_filtering": [],
            },
            {
                "host_names": ["traypublisher"],
                "product_types": ["matchmove", "shot"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": False,
                "advanced_filtering": [],
            },
            {
                "host_names": ["traypublisher"],
                "product_types": ["plate", "review", "audio"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": False,
                "advanced_filtering": [
                    {"families": ["clip", "review"], "add_kitsu_family": True}
                ],
            },
            {
                "host_names": ["maya"],
                "product_types": [
                    "model",
                    "setdress",
                    "animation",
                    "look",
                    "rig",
                    "camera",
                ],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": True,
                "advanced_filtering": [],
            },
            {
                "host_names": ["tvpaint"],
                "product_types": ["renderPass"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": False,
                "advanced_filtering": [],
            },
            {
                "host_names": ["tvpaint"],
                "product_types": [],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": True,
                "advanced_filtering": [],
            },
            {
                "host_names": ["nuke"],
                "product_types": ["write", "render", "prerender"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": False,
                "advanced_filtering": [
                    {"families": ["review"], "add_kitsu_family": True}
                ],
            },
            {
                "host_names": ["aftereffects"],
                "product_types": ["render", "workfile"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": True,
                "advanced_filtering": [],
            },
            {
                "host_names": ["flame"],
                "product_types": ["plate", "take"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": True,
                "advanced_filtering": [],
            },
            {
                "host_names": ["houdini"],
                "product_types": ["usd"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": True,
                "advanced_filtering": [],
            },
            {
                "host_names": ["photoshop"],
                "product_types": ["review"],
                "task_types": [],
                "task_names": [],
                "add_kitsu_family": True,
                "advanced_filtering": [],
            },
        ],
    },
    "IntegrateKitsuNote": {
        "set_status_note": False,
        "note_status_shortname": "wfa",
        "status_change_conditions": {
            "status_conditions": [],
            "family_requirements": [],
        },
        "custom_comment_template": {
            "enabled": False,
            "comment_template": """{comment}

|  |  |
|--|--|
| version | `{version}` |
| family | `{family}` |
| name | `{name}` |""",
        },
    },
}

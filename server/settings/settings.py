from pydantic import Field
from ayon_server.settings import BaseSettingsModel
from ayon_server.settings.enum import secrets_enum


class EntityPattern(BaseSettingsModel):
    episode: str = Field(title="Episode")
    sequence: str = Field(title="Sequence")
    shot: str = Field(title="Shot")


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


class StatusChangeFamilyRequirementModel(BaseSettingsModel):
    condition: str = Field(
        "equal", enum_resolver=_status_change_cond_enum, title="Condition"
    )
    product_type: str = Field("", title="Family")


class StatusChangeConditionsModel(BaseSettingsModel):
    status_conditions: list[StatusChangeCondition] = Field(
        default_factory=list, title="Status conditions"
    )
    family_requirements: list[StatusChangeFamilyRequirementModel] = Field(
        default_factory=list, title="Family requirements"
    )


class CustomCommentTemplateModel(BaseSettingsModel):
    enabled: bool = Field(True)
    comment_template: str = Field("", title="Custom comment")


class IntegrateKitsuNotes(BaseSettingsModel):
    """Kitsu supports markdown and here you can create a custom comment template.

    You can use data from your publishing instance's data.
    """

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


class KitsuSettings(BaseSettingsModel):
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

    entities_naming_pattern: EntityPattern = Field(
        default_factory=EntityPattern,
        title="Entities naming pattern",
    )
    publish: PublishPlugins = Field(
        default_factory=PublishPlugins,
        title="Publish plugins",
    )

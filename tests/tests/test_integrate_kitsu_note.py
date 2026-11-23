import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def note_plugin(monkeypatch):
    gazu = ModuleType("gazu")
    gazu.task = Mock()
    pyblish = ModuleType("pyblish")
    pyblish.api = ModuleType("pyblish.api")
    pyblish.api.IntegratorOrder = 3
    pipeline = ModuleType("ayon_kitsu.pipeline")
    pipeline.KitsuPublishContextPlugin = type("Plugin", (), {"log": Mock()})

    monkeypatch.setitem(sys.modules, "gazu", gazu)
    monkeypatch.setitem(sys.modules, "pyblish", pyblish)
    monkeypatch.setitem(sys.modules, "pyblish.api", pyblish.api)
    monkeypatch.setitem(sys.modules, "ayon_kitsu.pipeline", pipeline)

    root = Path(__file__).resolve().parents[2]
    path = root / "client/ayon_kitsu/plugins/publish/integrate_kitsu_note.py"
    plugin = runpy.run_path(str(path))["IntegrateKitsuNote"]()
    return plugin, gazu.task


@pytest.mark.parametrize(
    ("families", "requirements", "change_status"),
    [
        pytest.param(
            ["render", "workfile"],
            [("equal", "render")],
            True,
            id="mixed-families",
        ),
        pytest.param(
            ["renderPass"], [("equal", "RENDERPASS")], True, id="case"
        ),
        pytest.param(
            ["render"],
            [("equal", "workfile"), ("equal", "render")],
            True,
            id="second-requirement-matches",
        ),
        pytest.param(
            ["render"],
            [("equal", "render"), ("equal", "workfile")],
            True,
            id="first-requirement-matches",
        ),
        pytest.param(["render"], [("equal", "workfile")], False, id="missing"),
        pytest.param(
            ["render"],
            [("not_equal", "workfile")],
            True,
            id="absent-family",
        ),
        pytest.param(
            ["render", "Workfile"],
            [("not_equal", "workfile")],
            False,
            id="excluded-family",
        ),
        pytest.param(
            [], [("equal", "render")], False, id="no-enabled-families"
        ),
        pytest.param([], [], True, id="no-requirements"),
        pytest.param(
            ["render"], [("equal", "review")], False, id="secondary-family"
        ),
    ],
)
def test_note_status_family_requirements(
    note_plugin, families, requirements, change_status
):
    plugin, task_api = note_plugin
    plugin.set_status_note = True
    plugin.status_change_conditions = {
        "status_conditions": [],
        "family_requirements": [
            {"condition": condition, "product_type": product_type}
            for condition, product_type in requirements
        ],
    }
    task = {
        "id": "task-id",
        "task_status": {"short_name": "wip"},
        "task_status_id": "current-status-id",
    }
    target_status = {"id": "target-status-id", "short_name": "wfa"}
    task_api.get_task_status_by_short_name.return_value = target_status
    review = SimpleNamespace(
        data={
            "family": families[0] if families else "render",
            "families": ["review", "kitsu"],
            "kitsuTask": task,
            "publish": bool(families),
            "comment": "Publish note",
        }
    )
    instances = [
        SimpleNamespace(data={"family": family, "publish": True})
        for family in families[1:]
    ]

    plugin.process([review, *instances])

    expected_status = (
        target_status if change_status else task["task_status_id"]
    )
    task_api.add_comment.assert_called_once_with(
        task, expected_status, comment="Publish note"
    )

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
    ("products", "requirements", "change_status"),
    [
        pytest.param(
            [{"family": "render"}, {"family": "workfile"}],
            [("equal", "render")],
            True,
            id="mixed-families",
        ),
        pytest.param(
            [{"family": "renderPass"}],
            [("equal", "RENDERPASS")],
            True,
            id="case",
        ),
        pytest.param(
            [{"family": "render", "productType": "renderPass"}],
            [("equal", "RENDERPASS")],
            True,
            id="custom-product-type",
        ),
        pytest.param(
            [{"family": "render", "productType": "renderPass"}],
            [("equal", "render")],
            True,
            id="primary-family-with-custom-product-type",
        ),
        pytest.param(
            [{"family": "render", "productType": "renderPass"}],
            [("not_equal", "renderpass")],
            False,
            id="excluded-custom-product-type",
        ),
        pytest.param(
            [{"productType": "renderPass"}],
            [("equal", "renderpass")],
            True,
            id="missing-primary-family",
        ),
        pytest.param(
            [
                {"family": "render"},
                {"productType": "renderPass", "publish": False},
            ],
            [("equal", "renderpass")],
            False,
            id="disabled-custom-product-type",
        ),
        pytest.param(
            [{"family": "render"}],
            [("equal", "workfile"), ("equal", "render")],
            True,
            id="second-requirement-matches",
        ),
        pytest.param(
            [{"family": "render"}],
            [("equal", "render"), ("equal", "workfile")],
            True,
            id="first-requirement-matches",
        ),
        pytest.param(
            [{"family": "render"}],
            [("equal", "workfile")],
            False,
            id="missing",
        ),
        pytest.param(
            [{"family": "render"}],
            [("not_equal", "workfile")],
            True,
            id="absent-family",
        ),
        pytest.param(
            [{"family": "render"}, {"family": "Workfile"}],
            [("not_equal", "workfile")],
            False,
            id="excluded-family",
        ),
        pytest.param(
            [], [("equal", "render")], False, id="no-enabled-families"
        ),
        pytest.param([], [], True, id="no-requirements"),
        pytest.param(
            [{"family": "render"}],
            [("equal", "review")],
            False,
            id="secondary-family",
        ),
    ],
)
def test_note_status_family_requirements(
    note_plugin, products, requirements, change_status
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
            "families": ["review", "kitsu"],
            "kitsuTask": task,
            "publish": bool(products),
            "comment": "Publish note",
            **(products[0] if products else {}),
        }
    )
    instances = [
        SimpleNamespace(data={"publish": True, **product})
        for product in products[1:]
    ]

    plugin.process([review, *instances])

    expected_status = (
        target_status if change_status else task["task_status_id"]
    )
    task_api.add_comment.assert_called_once_with(
        task, expected_status, comment="Publish note"
    )


@pytest.mark.parametrize(
    ("set_status_note", "status_conditions"),
    [
        pytest.param(False, [], id="status-changes-disabled"),
        pytest.param(
            True,
            [{"condition": "equal", "short_name": "todo"}],
            id="current-status-does-not-match",
        ),
    ],
)
def test_matching_family_keeps_current_status_when_status_change_is_blocked(
    note_plugin, set_status_note, status_conditions
):
    plugin, task_api = note_plugin
    plugin.set_status_note = set_status_note
    plugin.status_change_conditions = {
        "status_conditions": status_conditions,
        "family_requirements": [
            {"condition": "equal", "product_type": "render"}
        ],
    }
    task = {
        "id": "task-id",
        "task_status": {"short_name": "wip"},
        "task_status_id": "current-status-id",
    }
    review = SimpleNamespace(
        data={
            "family": "render",
            "families": ["review", "kitsu"],
            "kitsuTask": task,
            "publish": True,
            "comment": "Publish note",
        }
    )

    plugin.process([review])

    task_api.get_task_status_by_short_name.assert_not_called()
    task_api.add_comment.assert_called_once_with(
        task, task["task_status_id"], comment="Publish note"
    )

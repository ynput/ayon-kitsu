"""Pinned example tests for attrib_parsing and inbound_mirror (Task 16.2).

Validates that extracted pure parsing modules preserve 100% of the
pre-refactor behavior from ``anatomy.py``, ``utils.calculate_end_frame``,
and ``utils.preprocess_task``.

Validates: Requirements 2.5, 7.2, 7.5, 8.7, 8.10, 14.8.
"""

from unittest.mock import MagicMock
import pytest

from attrib_parsing import end_frame_from_kitsu, parse_attrib
from processor.outbound.inbound_mirror import match_assignees_by_email

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")


def test_parse_attrib_nominal():
    """All supported Kitsu attributes are parsed into AYON equivalents."""
    source = {
        "fps": "24.0",
        "frame_in": "1001",
        "frame_out": "1050",
        "resolution": "1920x1080",
        "description": "A test sequence description.",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
    }
    result = parse_attrib(source)
    assert result == {
        "fps": 24.0,
        "frameStart": 1001,
        "frameEnd": 1050,
        "resolutionWidth": 1920,
        "resolutionHeight": 1080,
        "description": "A test sequence description.",
        "startDate": "2026-01-01T00:00:00Z",
        "endDate": "2026-01-31T00:00:00Z",
    }


def test_parse_attrib_empty_and_none():
    """Empty or None input produces an empty attribute dict."""
    assert parse_attrib(None) == {}
    assert parse_attrib({}) == {}
    assert parse_attrib({"fps": None, "description": None}) == {}


def test_parse_attrib_malformed_values():
    """Malformed numeric or resolution strings are safely ignored."""
    source = {
        "fps": "not-a-number",
        "frame_in": "bad_frame",
        "frame_out": "bad_frame",
        "resolution": "invalid_resolution",
    }
    result = parse_attrib(source)
    assert result == {}


def test_parse_attrib_empty_description_behavior():
    """Pinned behavior: empty description copied if passed, but caller omits.

    parse_attrib itself copies an explicit empty string, but the caller
    boundary in push.py uses ``if entity_dict.get('description'):`` which
    drops falsy/empty description strings before calling parse_attrib (F14,
    Requirement 8.10).
    """
    # parse_attrib direct behavior
    assert parse_attrib({"description": ""}) == {"description": ""}

    # push.py caller boundary behavior (falsy description omitted)
    entity_dict = {"description": ""}
    data = {}
    if entity_dict.get("description"):
        data["description"] = entity_dict["description"]
    assert "description" not in data
    assert "description" not in parse_attrib(data)


def test_end_frame_from_kitsu_nominal():
    """Truthy frame_out is returned directly."""
    entity = {"data": {"frame_out": 1050}}
    assert end_frame_from_kitsu(entity) == 1050


def test_end_frame_from_kitsu_falsy_fallback():
    """Falsy frame_out (0, None, '') falls back to nb_frames arithmetic."""
    # frame_out is 0 (falsy) -> falls back to frame_in + nb_frames - 1
    entity_zero = {
        "data": {"frame_out": 0, "frame_in": 1001},
        "nb_frames": 24,
    }
    assert end_frame_from_kitsu(entity_zero) == 1024

    # frame_out is None -> falls back to frame_in + nb_frames - 1
    entity_none = {
        "data": {"frame_out": None, "frame_in": 1001},
        "nb_frames": 10,
    }
    assert end_frame_from_kitsu(entity_none) == 1010


def test_end_frame_from_kitsu_folder_fallback():
    """Missing frame_in uses fallback_frame_start."""
    entity = {
        "data": {"frame_out": None, "frame_in": None},
        "nb_frames": 50,
    }
    assert end_frame_from_kitsu(entity, fallback_frame_start=1001) == 1050


def test_end_frame_from_kitsu_missing_data_or_concept():
    """Entities without data or nb_frames return None (including concepts)."""
    assert end_frame_from_kitsu({"data": None}) is None
    assert end_frame_from_kitsu({}) is None
    assert end_frame_from_kitsu({"data": "not-a-dict"}) is None
    assert end_frame_from_kitsu({"data": {}, "nb_frames": 0}) is None
    assert end_frame_from_kitsu({"data": {"frame_in": 1001}}) is None


def test_anatomy_reexports_parse_attrib():
    """anatomy.py imports and re-exports parse_attrib from .attrib_parsing."""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    anatomy_path = root / "server" / "kitsu" / "anatomy.py"
    tree = ast.parse(anatomy_path.read_text(encoding="utf-8"))
    imported = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "attrib_parsing":
                for alias in node.names:
                    if alias.name == "parse_attrib":
                        imported = True
    assert imported, "anatomy.py must re-export parse_attrib"


def test_utils_calculate_end_frame_delegates():
    """utils.calculate_end_frame delegates to end_frame_from_kitsu."""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent.parent
    utils_path = root / "server" / "kitsu" / "utils.py"
    tree = ast.parse(utils_path.read_text(encoding="utf-8"))
    delegated = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "calculate_end_frame"
        ):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func_name = getattr(sub.func, "id", None)
                    if func_name == "end_frame_from_kitsu":
                        delegated = True
    assert delegated, "utils.calculate_end_frame must delegate"


def test_match_assignees_by_email_nominal():
    """Nominal email matching resolves Kitsu emails to AYON usernames."""
    ayon_users = [
        {"name": "alice", "attrib": {"email": "alice@example.com"}},
        {"name": "bob", "attrib": {"email": "bob@example.com"}},
    ]
    matched = match_assignees_by_email(["alice@example.com"], ayon_users)
    assert matched == ["alice"]


def test_match_assignees_by_email_last_user_wins():
    """Duplicate emails in AYON exhibit 'last user wins' semantics (F13)."""
    ayon_users = [
        {"name": "alice_old", "attrib": {"email": "shared@example.com"}},
        {"name": "alice_new", "attrib": {"email": "shared@example.com"}},
    ]
    matched = match_assignees_by_email(["shared@example.com"], ayon_users)
    assert matched == ["alice_new"]


def test_match_assignees_by_email_case_sensitivity_and_unmatched():
    """Case-sensitive comparison and unmatched emails silently omitted."""
    ayon_users = [
        {"name": "alice", "attrib": {"email": "alice@example.com"}},
    ]
    # Case mismatch -> omitted
    assert match_assignees_by_email(["Alice@Example.com"], ayon_users) == []
    # Not found -> omitted
    assert match_assignees_by_email(["stranger@example.com"], ayon_users) == []
    # Empty inputs -> empty list
    assert match_assignees_by_email([], ayon_users) == []
    assert match_assignees_by_email(["alice@example.com"], []) == []

"""tests for endpoint 'api/addons/kitsu/{version}/push'
when some entities cannot be synced

$ poetry run pytest tests/test_push_errors.py
"""

from . import mock_data
from .fixtures import PROJECT_NAME, api, kitsu_url


def test_push_skips_invalid_entity(api, kitsu_url):
    # AYON refuses an apostrophe in a folder label
    invalid, valid = [dict(e) for e in mock_data.all_episodes_for_project]
    invalid["name"] = "Episode 'one'"

    res = api.post(
        f"{kitsu_url}/push",
        project_name=PROJECT_NAME,
        entities=[invalid, valid],
    )
    assert res.status_code == 200
    assert res.data["failed"] == ["episode-id-1"]
    assert "episode-id-1" not in res.data["folders"]
    assert "episode-id-2" in res.data["folders"]

    res = api.get(f"/projects/{PROJECT_NAME}/hierarchy")
    episodes_folder = res.data["hierarchy"][0]
    assert [f["name"] for f in episodes_folder["children"]] == ["episode_02"]

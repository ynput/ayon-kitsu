"""Live coverage of creation, rename, conflict pulls, retries, and deletion."""

import time
import uuid

import pytest

from processor.fullsync import project_full_sync
from processor.processor import KitsuProcessor

from .live_support import isolated_outbound_live  # noqa: F401
from .test_outbound_status_live import live_servers  # noqa: F401

pytestmark = [
    pytest.mark.live_servers,
    pytest.mark.usefixtures("isolated_outbound_live"),
]


def _wait_for(runner, check, timeout=30):
    """Process live events until the expected server state is visible.

    Args:
        runner: Outbound runner using the live API clients.
        check: Callable returning the expected state when it is ready.
        timeout: Maximum wait in seconds.

    Returns:
        The truthy state returned by the check.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        runner.poll_once()
        result = check()
        if result:
            return result
        time.sleep(0.2)
    pytest.fail("Live outbound state did not converge before the timeout")


def test_live_folder_lifecycle_conflict_and_retry(live_servers):
    """Drive the real runner through a folder's complete live lifecycle."""
    import ayon_api
    import gazu

    uid = uuid.uuid4().hex[:8]
    project_name = f"test_live_lifecycle_{uid}"
    user_api = ayon_api.ServerAPI(
        base_url=live_servers["ayon_url"], token=live_servers["ayon_key"]
    )
    kitsu_project = None
    processor = None
    try:
        kitsu_project = gazu.project.new_project(project_name)
        sequence = gazu.shot.new_sequence(kitsu_project, "SQ01")
        gazu.shot.new_shot(kitsu_project, sequence, "SH_SEED")
        response = user_api.put(
            f"projects/{project_name}",
            code=f"L{uid[:3].upper()}",
            data={"kitsuProjectId": kitsu_project["id"]},
            folderTypes=[
                {"name": name} for name in ("Folder", "Sequence", "Shot")
            ],
            taskTypes=[{"name": "Animation"}],
            statuses=[{"name": "Todo"}],
        )
        response.raise_for_status()
        processor = KitsuProcessor()
        processor.pairing_list = {kitsu_project["id"]: project_name}
        project_full_sync(processor, kitsu_project["id"], project_name)
        parent = next(
            folder
            for folder in user_api.get_folders(project_name)
            if (folder.get("data") or {}).get("kitsuId") == sequence["id"]
        )
        runner = processor.outbound
        assert runner is not None
        settings = user_api.get_addon_settings(
            "kitsu", processor.addon_version
        )
        settings["sync_settings"]["two_way_sync"].update(
            {
                "enabled": True,
                "entity_creation": True,
                "entity_rename": True,
                "entity_deletion": True,
                "conflict_policy": "kitsu_wins",
            }
        )
        response = user_api.post(
            f"addons/kitsu/{processor.addon_version}/settings/{project_name}",
            **settings,
        )
        response.raise_for_status()
        runner.gate_history.load(started_at=time.time())
        runner.settings_watcher.refresh()

        folder_id = user_api.create_folder(
            project_name,
            "sh_created",
            folder_type="Shot",
            parent_id=parent["id"],
        )
        kitsu_id = _wait_for(
            runner,
            lambda: (
                user_api.get_folder_by_id(project_name, folder_id).get("data")
                or {}
            ).get("kitsuId"),
        )
        assert gazu.shot.get_shot(kitsu_id)["name"] == "sh_created"

        # A real connection refusal must hold the job and retry successfully
        # after the dedicated writer is pointed back at the running Kitsu API.
        user_api.update_folder(project_name, folder_id, label="Retry Rename")
        real_host = gazu.client.get_host(client=runner.writer.client)
        gazu.client.set_host(
            "http://127.0.0.1:1/api", client=runner.writer.client
        )
        try:
            _wait_for(runner, lambda: runner.held_job, timeout=15)
            held = runner.held_job
            assert held["attempt"] == 2
            assert held["job"]["summary"]["errorKind"] == "unreachable"
            assert gazu.shot.get_shot(kitsu_id)["name"] == "sh_created"
        finally:
            gazu.client.set_host(real_host, client=runner.writer.client)
        _wait_for(
            runner,
            lambda: gazu.shot.get_shot(kitsu_id)["name"] == "Retry Rename",
        )

        # Queue a user rename, then create a concurrent Kitsu edit before the
        # runner handles it. The Kitsu-winning conflict must pull that edit.
        user_api.update_folder(project_name, folder_id, label="AYON Pending")
        shot = gazu.shot.get_shot(kitsu_id)
        shot["name"] = "Kitsu Winner"
        gazu.shot.update_shot(shot)
        _wait_for(
            runner,
            lambda: (
                user_api.get_folder_by_id(project_name, folder_id).get("label")
                == "Kitsu Winner"
            ),
        )
        _wait_for(runner, lambda: not runner.poll_once())
        jobs = list(user_api.get_events(topics=[runner.TARGET_TOPIC]))
        assert any(
            user_api.get_event(job["id"]).get("summary", {}).get("decision")
            == "conflict"
            for job in jobs
        )
        assert gazu.shot.get_shot(kitsu_id)["name"] == "Kitsu Winner"

        response = user_api.delete(
            f"projects/{project_name}/folders/{folder_id}"
        )
        response.raise_for_status()

        def deleted():
            try:
                gazu.shot.get_shot(kitsu_id)
            except gazu.exception.RouteNotFoundException:
                return True
            return False

        _wait_for(runner, deleted)
        shots = gazu.shot.all_shots_for_project(kitsu_project)
        assert [shot["name"] for shot in shots] == ["SH_SEED"]
    finally:
        if processor is not None:
            processor.stop()
            processor.event_client.disconnect()
        if kitsu_project is not None:
            gazu.log_in(live_servers["kitsu_login"], live_servers["kitsu_pwd"])
            gazu.project.close_project(kitsu_project)
            gazu.project.remove_project(kitsu_project, force=True)
        response = user_api.delete(f"projects/{project_name}")
        assert response.status_code in (200, 204, 404)

"""Live Slice 1 integration test for task status outbound sync.

Validates: Requirements 6.6, 14.5, 14.6, 14.7
"""

import os
import threading
import time
import uuid
from typing import Any, Dict, Generator, Tuple

import pytest

# Feature: kitsu-two-way-sync, Task 13: Live Slice 1 Integration Test
pytestmark = pytest.mark.live_servers


def _probe_server(url: str, timeout: float = 10.0) -> Tuple[bool, str]:
    """Probe an HTTP server with a strict timeout.

    Args:
        url: URL to probe.
        timeout: Timeout in seconds.

    Returns:
        Tuple of (reachable, error_message).
    """
    import httpx

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            # Accept any HTTP status response as proof of reachability
            if resp.status_code < 600:
                return True, ""
            return False, f"HTTP status {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


@pytest.fixture(scope="module")
def live_servers() -> Generator[Dict[str, Any], None, None]:
    """Probe AYON and Kitsu servers and yield authenticated context.

    Skips cleanly if either server is not configured or fails to respond
    within 10 s (Requirement 14.6).
    """
    ayon_url = os.environ.get("AYON_SERVER_URL")
    ayon_key = os.environ.get("AYON_API_KEY")
    kitsu_url = os.environ.get("KITSU_API_URL")
    kitsu_login = os.environ.get("KITSU_LOGIN")
    kitsu_pwd = os.environ.get("KITSU_PWD")

    if not ayon_url or not ayon_key:
        pytest.skip(
            "AYON server unavailable: AYON_SERVER_URL or AYON_API_KEY missing"
        )
    if not kitsu_url or not kitsu_login or not kitsu_pwd:
        pytest.skip(
            "Kitsu server unavailable: KITSU_API_URL, KITSU_LOGIN or "
            "KITSU_PWD missing"
        )

    # 10 s probe for AYON server
    ayon_probe_url = f"{ayon_url.rstrip('/')}/api/info"
    ayon_ok, ayon_err = _probe_server(ayon_probe_url, timeout=10.0)
    if not ayon_ok:
        pytest.skip(f"AYON server unavailable at {ayon_probe_url}: {ayon_err}")

    # 10 s probe for Kitsu server
    kitsu_probe_url = f"{kitsu_url.rstrip('/')}/"
    kitsu_ok, kitsu_err = _probe_server(kitsu_probe_url, timeout=10.0)
    if not kitsu_ok:
        pytest.skip(
            f"Kitsu server unavailable at {kitsu_probe_url}: {kitsu_err}"
        )

    # Authenticate with gazu
    import gazu

    try:
        gazu.client.set_host(kitsu_url.rstrip("/"))
        gazu.log_in(kitsu_login, kitsu_pwd)
    except Exception as exc:
        pytest.skip(f"Kitsu login failed: {exc}")

    # Authenticate with ayon_api
    import ayon_api

    try:
        ayon_api.init_service()
    except Exception as exc:
        pytest.skip(f"AYON init_service failed: {exc}")

    yield {
        "ayon_url": ayon_url,
        "ayon_key": ayon_key,
        "kitsu_url": kitsu_url,
        "kitsu_login": kitsu_login,
        "kitsu_pwd": kitsu_pwd,
        "gazu": gazu,
        "ayon_api": ayon_api,
    }

    try:
        gazu.log_out()
    except Exception:
        pass


def _events_for_entity(
    api: Any, topic: str, proj: str, entity_id: str
) -> list[dict[str, Any]]:
    matching = []
    for e in api.get_events(topics=[topic], project_names=[proj]):
        full_e = api.get_event(e["id"])
        if (full_e.get("summary") or {}).get("entityId") == entity_id:
            matching.append(full_e)
    return matching


def test_live_task_status_outbound_sync(
    live_servers: Dict[str, Any],
) -> None:
    """Live integration test for task status outbound sync and bounded echo.

    Validates: Requirements 6.6, 14.5, 14.6, 14.7
    """
    gazu = live_servers["gazu"]
    ayon_api = live_servers["ayon_api"]

    # Generate unique names
    uid = uuid.uuid4().hex[:6]
    proj_code = f"L{uid[:3].upper()}"
    proj_name = f"test_live_status_{uid}"

    kitsu_project = None
    processor = None
    proc_thread = None

    try:
        # 1. Create Kitsu project with sequence, 2 shots, and tasks
        kitsu_project = gazu.project.new_project(proj_name)
        seq = gazu.shot.new_sequence(kitsu_project, "SQ01")
        shot1 = gazu.shot.new_shot(kitsu_project, seq, "SH01")
        shot2 = gazu.shot.new_shot(kitsu_project, seq, "SH02")

        task_type = (
            gazu.task.get_task_type_by_name("Animation")
            or gazu.task.new_task_type("Animation")
        )
        status_todo = (
            gazu.task.get_task_status_by_name("Todo")
            or gazu.task.new_task_status("Todo", "todo")
        )
        status_approved = (
            gazu.task.get_task_status_by_name("Approved")
            or gazu.task.new_task_status("Approved", "approved")
        )

        gazu.project.add_task_type(kitsu_project, task_type, 1)
        gazu.project.add_task_status(kitsu_project, status_todo)
        gazu.project.add_task_status(kitsu_project, status_approved)

        task1 = gazu.task.new_task(shot1, task_type, task_status=status_todo)
        gazu.task.new_task(shot2, task_type, task_status=status_todo)

        # 2. Create paired AYON project
        project_meta = {
            "code": proj_code,
            "data": {"kitsuProjectId": kitsu_project["id"]},
            "folderTypes": [
                {"name": "Folder"},
                {"name": "Sequence"},
                {"name": "Shot"},
            ],
            "taskTypes": [{"name": "Animation"}],
            "statuses": [{"name": "Todo"}, {"name": "Approved"}],
        }
        ayon_api.put(f"/projects/{proj_name}", **project_meta)

        # 3. Start in-process KitsuProcessor in daemon thread
        from processor.processor import KitsuProcessor

        processor = KitsuProcessor()
        processor.pairing_list = {kitsu_project["id"]: proj_name}
        proc_thread = threading.Thread(
            target=processor.start_processing,
            daemon=True,
        )
        proc_thread.start()

        # Wait for full sync to create AYON task with kitsuId
        ayon_task_id = None
        start_wait = time.time()
        while time.time() - start_wait < 30.0:
            tasks = list(ayon_api.get_tasks(proj_name))
            for t in tasks:
                if (t.get("data") or {}).get("kitsuId") == task1["id"]:
                    ayon_task_id = t["id"]
                    break
            if ayon_task_id:
                break
            time.sleep(1.0)

        assert ayon_task_id is not None, "Full sync timed out creating task"

        # 4. Enable master toggle and task_status category in project settings
        if getattr(processor, "outbound", None):
            addon_name = processor.addon_name
            addon_version = processor.addon_version
            settings_url = (
                f"addons/{addon_name}/{addon_version}/settings/{proj_name}"
            )
            proj_settings = (
                ayon_api.get_addon_settings(addon_name, addon_version) or {}
            )
            two_way = proj_settings.setdefault(
                "sync_settings", {}
            ).setdefault("two_way_sync", {})
            two_way["enabled"] = True
            two_way["task_status"] = True
            two_way["task_assignees"] = False
            two_way["entity_attributes"] = False
            two_way["entity_creation"] = False
            two_way["entity_rename"] = False
            two_way["entity_deletion"] = False
            post_res = ayon_api.post(settings_url, **proj_settings)
            assert post_res.status_code in (200, 201, 204), (
                f"Failed to post project settings: {post_res.status_code}"
            )
            processor.outbound.settings_watcher.refresh()

        # Create independent user client for unpolluted origin (Req 5.5, 5.8)
        from ayon_api import ServerAPI

        user_api = ServerAPI(
            base_url=live_servers["ayon_url"],
            token=live_servers["ayon_key"],
        )

        # 5. Record initial Kitsu comments and AYON status change events
        initial_comments = len(gazu.task.all_comments_for_task(task1))
        initial_status_events = _events_for_entity(
            user_api, "entity.task.status_changed", proj_name, ayon_task_id
        )
        initial_update_events = _events_for_entity(
            user_api, "entity.task.updated", proj_name, ayon_task_id
        )

        # 6. Change AYON task status to "Approved" via independent user client
        user_api.update_task(proj_name, ayon_task_id, status="Approved")

        # 7. Assert Kitsu task status updated within 30 s
        kitsu_updated = False
        start_check = time.time()
        while time.time() - start_check < 30.0:
            current_kitsu_task = gazu.task.get_task(task1["id"])
            if (
                current_kitsu_task.get("task_status_id")
                == status_approved["id"]
            ):
                kitsu_updated = True
                break
            time.sleep(1.0)

        assert kitsu_updated, "Kitsu status not updated within 30 seconds"

        # Assert exactly one new status comment in Kitsu
        new_comments = len(gazu.task.all_comments_for_task(task1))
        assert new_comments == initial_comments + 1

        # 8. Assert no further change in next 60 s (bounded echo, Req 5.5)
        # At most 1 Kitsu write and 0 subsequent AYON writes.
        time.sleep(60.0)
        comments_after_wait = len(gazu.task.all_comments_for_task(task1))
        assert comments_after_wait == initial_comments + 1

        task_after_wait = gazu.task.get_task(task1["id"])
        assert task_after_wait.get("task_status_id") == status_approved["id"]

        # Assert exactly 1 AYON status event occurred (the user change itself)
        # and zero echo writes from Inbound_Sync (Req 5.5)
        final_status_events = _events_for_entity(
            user_api, "entity.task.status_changed", proj_name, ayon_task_id
        )
        final_update_events = _events_for_entity(
            user_api, "entity.task.updated", proj_name, ayon_task_id
        )
        extra_status = (
            len(final_status_events) - len(initial_status_events) - 1
        )
        assert len(final_status_events) == len(initial_status_events) + 1, (
            f"Expected 0 echo writes in AYON, found {extra_status} extra"
        )
        # Inbound /push writes emit entity.task.updated
        assert len(final_update_events) == len(initial_update_events), (
            f"Expected 0 entity.task.updated echo writes, found "
            f"{len(final_update_events) - len(initial_update_events)} extra"
        )

    finally:
        # Teardown: stop processor and join worker thread
        thread_join_err = None
        try:
            if processor is not None:
                processor.stop()
            if proc_thread is not None and proc_thread.is_alive():
                proc_thread.join(timeout=10.0)
                if proc_thread.is_alive():
                    thread_join_err = RuntimeError(
                        "Processor worker thread did not stop within 10s"
                    )
        except Exception as exc:
            thread_join_err = exc

        # Teardown ALWAYS deletes AYON project and Kitsu project (Req 14.7)
        kitsu_cleanup_err = None
        if kitsu_project is not None:
            try:
                gazu.log_in(
                    live_servers["kitsu_login"],
                    live_servers["kitsu_pwd"],
                )
                gazu.project.close_project(kitsu_project)
                gazu.project.remove_project(kitsu_project, force=True)
            except Exception as exc:
                kitsu_cleanup_err = exc

        ayon_cleanup_err = None
        try:
            ayon_api.delete(f"/projects/{proj_name}")
        except Exception as exc:
            ayon_cleanup_err = exc

        if thread_join_err or kitsu_cleanup_err or ayon_cleanup_err:
            raise RuntimeError(
                f"Teardown failed: thread={thread_join_err}, "
                f"kitsu={kitsu_cleanup_err}, ayon={ayon_cleanup_err}"
            )

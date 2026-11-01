"""Live Slice 2 integration tests for task assignees and entity attributes.

Validates: Requirements 7.7, 8.4, 8.11, 14.6, 14.7
"""

import os
import threading
import time
import uuid
from typing import Any, Dict, Generator, Tuple

import pytest

# Feature: kitsu-two-way-sync, Task 20.2: Live Slice 2 Integration Tests
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

    ayon_probe_url = f"{ayon_url.rstrip('/')}/api/info"
    ayon_ok, ayon_err = _probe_server(ayon_probe_url, timeout=10.0)
    if not ayon_ok:
        pytest.skip(f"AYON server unavailable at {ayon_probe_url}: {ayon_err}")

    kitsu_probe_url = f"{kitsu_url.rstrip('/')}/"
    kitsu_ok, kitsu_err = _probe_server(kitsu_probe_url, timeout=10.0)
    if not kitsu_ok:
        pytest.skip(
            f"Kitsu server unavailable at {kitsu_probe_url}: {kitsu_err}"
        )

    import gazu

    try:
        gazu.client.set_host(kitsu_url.rstrip("/"))
        gazu.log_in(kitsu_login, kitsu_pwd)
    except Exception as exc:
        pytest.skip(f"Kitsu login failed: {exc}")

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


def test_live_task_assignees_outbound_sync(
    live_servers: Dict[str, Any],
) -> None:
    """Live integration test for task assignees sync within 30s.

    Validates: Requirements 7.7, 14.6, 14.7
    """
    gazu = live_servers["gazu"]
    ayon_api = live_servers["ayon_api"]

    uid = uuid.uuid4().hex[:6]
    proj_code = f"L{uid[:3].upper()}"
    proj_name = f"test_live_assignees_{uid}"

    kitsu_project = None
    processor = None
    proc_thread = None

    try:
        kitsu_project = gazu.project.new_project(proj_name)
        seq = gazu.shot.new_sequence(kitsu_project, "SQ01")
        shot1 = gazu.shot.new_shot(kitsu_project, seq, "SH01")

        task_type = (
            gazu.task.get_task_type_by_name("Animation")
            or gazu.task.new_task_type("Animation")
        )
        status_todo = (
            gazu.task.get_task_status_by_name("Todo")
            or gazu.task.new_task_status("Todo", "todo")
        )
        gazu.project.add_task_type(kitsu_project, task_type, 1)
        gazu.project.add_task_status(kitsu_project, status_todo)
        task1 = gazu.task.new_task(shot1, task_type, task_status=status_todo)

        # Get or create person in Kitsu
        persons = gazu.person.all_persons()
        if not persons:
            person = gazu.person.new_person(
                "Artist", "One", f"artist_{uid}@studio.com", "user"
            )
        else:
            person = persons[0]

        project_meta = {
            "code": proj_code,
            "data": {"kitsuProjectId": kitsu_project["id"]},
            "folderTypes": [
                {"name": "Folder"},
                {"name": "Sequence"},
                {"name": "Shot"},
            ],
            "taskTypes": [{"name": "Animation"}],
            "statuses": [{"name": "Todo"}],
        }
        ayon_api.put(f"/projects/{proj_name}", **project_meta)

        from processor.processor import KitsuProcessor

        processor = KitsuProcessor()
        processor.pairing_list = {kitsu_project["id"]: proj_name}
        proc_thread = threading.Thread(
            target=processor.start_processing,
            daemon=True,
        )
        proc_thread.start()

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
            two_way["task_status"] = False
            two_way["task_assignees"] = True
            two_way["entity_attributes"] = False
            two_way["entity_creation"] = False
            two_way["entity_rename"] = False
            two_way["entity_deletion"] = False
            post_res = ayon_api.post(settings_url, **proj_settings)
            assert post_res.status_code in (200, 201, 204), (
                f"Failed to post project settings: {post_res.status_code}"
            )
            processor.outbound.settings_watcher.refresh()

        from ayon_api import ServerAPI

        user_api = ServerAPI(
            base_url=live_servers["ayon_url"],
            token=live_servers["ayon_key"],
        )

        # Ensure user exists in AYON with person's email
        current_users = list(user_api.get_users())
        target_username = None
        for u in current_users:
            u_email = (u.get("attrib") or {}).get("email")
            if u_email and u_email == person.get("email"):
                target_username = u["name"]
                break

        if not target_username:
            target_username = f"artist_{uid}"
            user_api.post(
                "/users",
                name=target_username,
                attrib={"email": person.get("email")},
            )

        # Record initial Kitsu assignees and AYON events
        initial_kitsu_task = gazu.task.get_task(task1["id"])
        initial_kitsu_assignees = (
            initial_kitsu_task.get("assignees") or []
        )
        assert person["id"] not in initial_kitsu_assignees
        initial_assignee_events = _events_for_entity(
            user_api, "entity.task.assignees_changed", proj_name, ayon_task_id
        )
        initial_update_events = _events_for_entity(
            user_api, "entity.task.updated", proj_name, ayon_task_id
        )

        # Update task assignees in AYON
        user_api.patch(
            f"/projects/{proj_name}/tasks/{ayon_task_id}",
            assignees=[target_username],
        )

        # Assert Kitsu task assignees updated within 30 s (Req 7.7)
        kitsu_updated = False
        start_check = time.time()
        while time.time() - start_check < 30.0:
            current_kitsu_task = gazu.task.get_task(task1["id"])
            current_assignees = current_kitsu_task.get("assignees") or []
            if person["id"] in current_assignees:
                kitsu_updated = True
                break
            time.sleep(1.0)

        assert kitsu_updated, "Kitsu assignees not updated within 30 seconds"

        # Bounded echo: wait 60s, assert no extra echo writes in AYON
        time.sleep(60.0)
        final_kitsu_task = gazu.task.get_task(task1["id"])
        final_assignees = final_kitsu_task.get("assignees") or []
        assert person["id"] in final_assignees

        final_assignee_events = _events_for_entity(
            user_api, "entity.task.assignees_changed", proj_name, ayon_task_id
        )
        final_update_events = _events_for_entity(
            user_api, "entity.task.updated", proj_name, ayon_task_id
        )
        extra_assignee = (
            len(final_assignee_events) - len(initial_assignee_events) - 1
        )
        expected_assignee_count = len(initial_assignee_events) + 1
        assert len(final_assignee_events) == expected_assignee_count, (
            f"Expected 0 echo writes in AYON, found {extra_assignee} extra"
        )
        assert len(final_update_events) == len(initial_update_events), (
            f"Expected 0 entity.task.updated echo writes, found "
            f"{len(final_update_events) - len(initial_update_events)} extra"
        )

    finally:
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


def test_live_entity_attributes_outbound_sync(
    live_servers: Dict[str, Any],
) -> None:
    """Live integration test for entity attributes sync within 30s.

    Validates: Requirements 8.4, 8.11, 14.6, 14.7
    """
    gazu = live_servers["gazu"]
    ayon_api = live_servers["ayon_api"]

    uid = uuid.uuid4().hex[:6]
    proj_code = f"L{uid[:3].upper()}"
    proj_name = f"test_live_attrib_{uid}"

    kitsu_project = None
    processor = None
    proc_thread = None

    try:
        kitsu_project = gazu.project.new_project(proj_name)
        seq = gazu.shot.new_sequence(kitsu_project, "SQ01")
        shot1 = gazu.shot.new_shot(kitsu_project, seq, "SH01")

        # Set unrelated data key on Kitsu entity (Req 8.4)
        gazu.shot.update_shot_data(
            shot1,
            {"custom_unrelated_key": "live_unrelated_value"},
        )

        project_meta = {
            "code": proj_code,
            "data": {"kitsuProjectId": kitsu_project["id"]},
            "folderTypes": [
                {"name": "Folder"},
                {"name": "Sequence"},
                {"name": "Shot"},
            ],
            "taskTypes": [{"name": "Animation"}],
            "statuses": [{"name": "Todo"}],
        }
        ayon_api.put(f"/projects/{proj_name}", **project_meta)

        from processor.processor import KitsuProcessor

        processor = KitsuProcessor()
        processor.pairing_list = {kitsu_project["id"]: proj_name}
        proc_thread = threading.Thread(
            target=processor.start_processing,
            daemon=True,
        )
        proc_thread.start()

        ayon_folder_id = None
        start_wait = time.time()
        while time.time() - start_wait < 30.0:
            folders = list(ayon_api.get_folders(proj_name))
            for f in folders:
                if (f.get("data") or {}).get("kitsuId") == shot1["id"]:
                    ayon_folder_id = f["id"]
                    break
            if ayon_folder_id:
                break
            time.sleep(1.0)

        assert (
            ayon_folder_id is not None
        ), "Full sync timed out creating folder"

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
            two_way["task_status"] = False
            two_way["task_assignees"] = False
            two_way["entity_attributes"] = True
            two_way["entity_creation"] = False
            two_way["entity_rename"] = False
            two_way["entity_deletion"] = False
            post_res = ayon_api.post(settings_url, **proj_settings)
            assert post_res.status_code in (200, 201, 204), (
                f"Failed to post project settings: {post_res.status_code}"
            )
            processor.outbound.settings_watcher.refresh()

        from ayon_api import ServerAPI

        user_api = ServerAPI(
            base_url=live_servers["ayon_url"],
            token=live_servers["ayon_key"],
        )

        # Record initial Kitsu state and AYON events
        initial_shot = gazu.shot.get_shot(shot1["id"])
        initial_shot_data = initial_shot.get("data") or {}
        assert initial_shot_data.get("fps") != 30.0

        initial_attrib_events = _events_for_entity(
            user_api, "entity.folder.attrib_changed", proj_name, ayon_folder_id
        )
        initial_update_events = _events_for_entity(
            user_api, "entity.folder.updated", proj_name, ayon_folder_id
        )

        # Update attributes in AYON
        user_api.patch(
            f"/projects/{proj_name}/folders/{ayon_folder_id}",
            attrib={
                "fps": 30.0,
                "frameStart": 1001,
                "frameEnd": 1150,
                "description": f"Live test {uid}",
            },
        )

        # Assert Kitsu entity updated within 30 s (Req 8.11)
        # Verify every attribute sent: fps, frame_in, frame_out, description
        kitsu_updated = False
        start_check = time.time()
        while time.time() - start_check < 30.0:
            current_shot = gazu.shot.get_shot(shot1["id"])
            shot_data = current_shot.get("data") or {}
            if (
                shot_data.get("fps") == 30.0
                and shot_data.get("frame_in") == 1001
                and shot_data.get("frame_out") == 1150
                and current_shot.get("description") == f"Live test {uid}"
            ):
                kitsu_updated = True
                break
            time.sleep(1.0)

        assert kitsu_updated, "Kitsu attributes not updated within 30 seconds"

        # Requirement 8.4: Unrelated data keys strictly preserved
        current_shot = gazu.shot.get_shot(shot1["id"])
        current_data = current_shot.get("data") or {}
        assert (
            current_data.get("custom_unrelated_key")
            == "live_unrelated_value"
        )

        # Bounded echo: wait 60s, assert no extra echo writes in AYON
        time.sleep(60.0)
        final_shot = gazu.shot.get_shot(shot1["id"])
        final_data = final_shot.get("data") or {}
        assert final_data.get("fps") == 30.0
        assert final_data.get("frame_in") == 1001
        assert final_data.get("frame_out") == 1150
        assert final_shot.get("description") == f"Live test {uid}"

        final_attrib_events = _events_for_entity(
            user_api, "entity.folder.attrib_changed", proj_name, ayon_folder_id
        )
        final_update_events = _events_for_entity(
            user_api, "entity.folder.updated", proj_name, ayon_folder_id
        )
        extra_attrib = (
            len(final_attrib_events) - len(initial_attrib_events) - 1
        )
        expected_attrib_count = len(initial_attrib_events) + 1
        assert len(final_attrib_events) == expected_attrib_count, (
            f"Expected 0 echo writes in AYON, found {extra_attrib} extra"
        )
        assert len(final_update_events) == len(initial_update_events), (
            f"Expected 0 entity.folder.updated echo writes, found "
            f"{len(final_update_events) - len(initial_update_events)} extra"
        )

    finally:
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

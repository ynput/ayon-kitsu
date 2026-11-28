"""Offline unit tests for Kitsu sync feedback across processor and server."""

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from processor import fullsync
from processor.processor import KitsuProcessor

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_coro(coro):
    """Drive a pure coroutine without creating an OS event-loop socketpair."""
    try:
        while True:
            coro.send(None)
    except StopIteration as stop:
        return stop.value


class _FakeHttpResponse:
    """Minimal HTTP response object resembling ayon_api RestApiResponse."""

    def __init__(
        self,
        status_code: int = 200,
        detail: str = "",
        raise_exc: Exception | None = None,
    ):
        self.status_code = status_code
        self.detail = detail
        self.text = detail
        self._raise_exc = raise_exc

    def raise_for_status(self) -> None:
        if self._raise_exc is not None:
            raise self._raise_exc


class _RecordingAyonClient:
    """In-memory AYON client recording event dispatch and updates."""

    def __init__(self):
        self.source_events: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def add_sync_request(
        self, project_name: str, kitsu_project_id: str
    ) -> str:
        self._counter += 1
        req_id = f"req-{self._counter}"
        self.source_events[req_id] = {
            "id": req_id,
            "topic": "kitsu.sync_request",
            "project": project_name,
            "summary": {"kitsuProjectId": kitsu_project_id},
        }
        return req_id

    def enroll_event_job(
        self,
        source_topic: str,
        target_topic: str,
        sender: str,
        **_kwargs: Any,
    ) -> dict[str, Any] | None:
        for req_id, src in self.source_events.items():
            if src["topic"] != source_topic:
                continue
            already = any(
                ev.get("dependsOn") == req_id
                for ev in self.events.values()
            )
            if already:
                continue
            self._counter += 1
            job_id = f"job-{self._counter}"
            job = {
                "id": job_id,
                "dependsOn": req_id,
                "topic": target_topic,
                "sender": sender,
                "status": "pending",
                "description": "",
                "payload": {},
                "project": src["project"],
            }
            self.events[job_id] = job
            return dict(job)
        return None

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        if event_id in self.source_events:
            return dict(self.source_events[event_id])
        if event_id in self.events:
            return dict(self.events[event_id])
        return None

    def dispatch_event(
        self,
        topic: str,
        *,
        sender: str | None = None,
        project_name: str | None = None,
        description: str | None = None,
        payload: dict[str, Any] | None = None,
        finished: bool = True,
        **_kwargs: Any,
    ) -> SimpleNamespace:
        self._counter += 1
        ev_id = f"ev-{self._counter}"
        self.events[ev_id] = {
            "id": ev_id,
            "topic": topic,
            "sender": sender,
            "project": project_name,
            "description": description or "",
            "payload": dict(payload or {}),
            "status": "finished" if finished else "pending",
        }
        return SimpleNamespace(data={"id": ev_id})

    def update_event(
        self,
        event_id: str,
        *,
        sender: str | None = None,
        project_name: str | None = None,
        status: str | None = None,
        description: str | None = None,
        payload: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> None:
        ev = self.events[event_id]
        if sender is not None:
            ev["sender"] = sender
        if project_name is not None:
            ev["project"] = project_name
        if status is not None:
            ev["status"] = status
        if description is not None:
            ev["description"] = description
        if payload is not None:
            ev["payload"] = dict(payload)


def _make_processor(client: _RecordingAyonClient) -> KitsuProcessor:
    """Create a bare KitsuProcessor instance wired to a recording client."""
    proc = object.__new__(KitsuProcessor)
    proc.ayon_api = client
    proc.entrypoint = "/addons/kitsu/1.2.4"
    proc.pairing_list = {"kitsu-p1": "proj1"}
    proc.kitsu_login_email = "bot@studio.example"
    proc.kitsu_login_password = "super-secret-password"
    proc.outbound = None
    return proc


# ---------------------------------------------------------------------------
# Fullsync HTTP push error propagation
# ---------------------------------------------------------------------------


def test_raise_for_push_error_allows_success_and_none():
    """HTTP 200 and None responses do not raise."""
    fullsync._raise_for_push_error(None)
    fullsync._raise_for_push_error(_FakeHttpResponse(200))


def test_raise_for_push_error_propagates_raise_for_status():
    """HTTP error raised by raise_for_status propagates."""
    resp = _FakeHttpResponse(
        500,
        detail="Internal error",
        raise_exc=RuntimeError("500 Internal Server Error"),
    )
    with pytest.raises(RuntimeError, match="500 Internal Server Error"):
        fullsync._raise_for_push_error(resp)


def test_raise_for_push_error_raises_on_error_status_code():
    """HTTP >= 400 status code raises even if raise_for_status is a no-op."""
    resp = _FakeHttpResponse(403, detail="Forbidden")
    with pytest.raises(RuntimeError, match="HTTP status 403: Forbidden"):
        fullsync._raise_for_push_error(resp)


# ---------------------------------------------------------------------------
# Manual full sync event payload & redaction
# ---------------------------------------------------------------------------


def test_poll_sync_request_failure_records_error_payload_and_redacts(
    monkeypatch,
):
    """Failed kitsu.sync records sanitized error message and traceback."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)
    req_id = client.add_sync_request("proj1", "kitsu-p1")

    def failing_full_sync(_parent, _kitsu_id, _proj):
        raise RuntimeError(
            "Kitsu auth failed for bot@studio.example / super-secret-password"
        )

    monkeypatch.setattr(
        "processor.processor.project_full_sync", failing_full_sync
    )

    assert proc._poll_sync_request_once() is True

    sync_jobs = [
        ev for ev in client.events.values() if ev["topic"] == "kitsu.sync"
    ]
    assert len(sync_jobs) == 1
    job = sync_jobs[0]
    assert job["dependsOn"] == req_id
    assert job["status"] == "failed"
    assert job["description"].startswith("Sync failed:")
    assert "super-secret-password" not in job["description"]
    assert "bot@studio.example" not in job["description"]
    assert "error" in job["payload"]
    assert "message" in job["payload"]
    assert "super-secret-password" not in job["payload"]["error"]
    assert "super-secret-password" not in job["payload"]["message"]
    assert "Traceback" in job["payload"]["message"]


def test_poll_sync_request_success_clears_payload(monkeypatch):
    """Successful kitsu.sync sets status=finished and clears stale payload."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)
    client.add_sync_request("proj1", "kitsu-p1")

    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *_a, **_k: None
    )

    assert proc._poll_sync_request_once() is True

    sync_jobs = [
        ev for ev in client.events.values() if ev["topic"] == "kitsu.sync"
    ]
    assert len(sync_jobs) == 1
    assert sync_jobs[0]["status"] == "finished"
    assert sync_jobs[0]["description"] == "Kitsu sync finished"
    assert sync_jobs[0]["payload"] == {}


# ---------------------------------------------------------------------------
# Inbound Socket.IO error reporting
# ---------------------------------------------------------------------------


def test_run_inbound_handler_records_failed_event_on_exception():
    """Uncaught inbound exception creates a failed kitsu.inbound_sync event."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)

    def broken_handler(_proc, _data):
        raise ValueError("Shot missing parent with super-secret-password")

    result = proc._run_inbound_handler(
        "shot:update",
        broken_handler,
        {"project_id": "kitsu-p1", "shot_id": "s-1"},
    )
    assert result is None

    inbound_events = [
        ev
        for ev in client.events.values()
        if ev["topic"] == "kitsu.inbound_sync"
    ]
    assert len(inbound_events) == 1
    ev = inbound_events[0]
    assert ev["status"] == "failed"
    assert ev["project"] == "proj1"
    assert "Inbound shot:update failed:" in ev["description"]
    assert "super-secret-password" not in ev["description"]
    assert ev["payload"]["event"] == "shot:update"
    assert "super-secret-password" not in ev["payload"]["error"]
    assert "Traceback" in ev["payload"]["message"]


def test_run_inbound_handler_records_failed_event_on_http_error():
    """HTTP >= 400 response from /push records a failed kitsu.inbound_sync."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)

    def http_500_handler(_proc, _data):
        return _FakeHttpResponse(500, detail="DB error")

    result = proc._run_inbound_handler(
        "task:update",
        http_500_handler,
        {"project_id": "kitsu-p1", "task_id": "t-1"},
    )
    assert result is None

    inbound_events = [
        ev
        for ev in client.events.values()
        if ev["topic"] == "kitsu.inbound_sync"
    ]
    assert len(inbound_events) == 1
    assert inbound_events[0]["status"] == "failed"
    assert "HTTP 500: DB error" in inbound_events[0]["description"]


def test_run_inbound_handler_success_does_not_emit_error_event():
    """Successful inbound handler returns response and emits no error event."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)

    ok_resp = _FakeHttpResponse(200)
    result = proc._run_inbound_handler(
        "asset:update",
        lambda _p, _d: ok_resp,
        {"project_id": "kitsu-p1", "asset_id": "a-1"},
    )
    assert result is ok_resp
    assert not [
        ev
        for ev in client.events.values()
        if ev["topic"] == "kitsu.inbound_sync"
    ]


# ---------------------------------------------------------------------------
# Service-level log.error reporting
# ---------------------------------------------------------------------------


def test_dispatch_service_error_emits_redacted_log_error():
    """_dispatch_service_error records log.error with redacted secrets."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)

    proc._dispatch_service_error(
        "Login failed for bot@studio.example with super-secret-password",
        traceback_text="Traceback: super-secret-password",
        project_name="proj1",
    )

    log_errors = [
        ev for ev in client.events.values() if ev["topic"] == "log.error"
    ]
    assert len(log_errors) == 1
    ev = log_errors[0]
    assert ev["project"] == "proj1"
    assert ev["description"] == "Kitsu processor error"
    assert "super-secret-password" not in ev["payload"]["message"]
    assert "bot@studio.example" not in ev["payload"]["message"]
    assert "super-secret-password" not in ev["payload"]["traceback"]


def test_read_kitsu_secret_reports_http_errors():
    """HTTP 404/403 from get_secret dispatches log.error and raises."""
    from processor.processor import KitsuSettingsError

    client = _RecordingAyonClient()

    def failing_get_secret(name: str):
        raise RuntimeError(f"404 Not Found: secret {name}")

    client.get_secret = failing_get_secret
    proc = _make_processor(client)

    with pytest.raises(KitsuSettingsError, match="kitsu_pwd_secret"):
        proc._read_kitsu_secret("kitsu_pwd_secret", "password")

    log_errors = [
        ev for ev in client.events.values() if ev["topic"] == "log.error"
    ]
    assert len(log_errors) == 1
    assert "kitsu_pwd_secret" in log_errors[0]["payload"]["message"]


def test_startup_full_sync_records_kitsu_sync_status(monkeypatch):
    """Startup full sync writes kitsu.sync finished/failed status."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)

    # 1. Success path
    monkeypatch.setattr(
        "processor.processor.project_full_sync", lambda *_a, **_k: None
    )
    assert proc._run_startup_full_sync("kitsu-p1", "proj1") is True
    sync_events = [
        ev for ev in client.events.values() if ev["topic"] == "kitsu.sync"
    ]
    assert len(sync_events) == 1
    assert sync_events[0]["status"] == "finished"
    assert sync_events[0]["project"] == "proj1"

    # 2. Failure path
    def boom(*_a, **_k):
        raise RuntimeError("Push 500 with super-secret-password")

    monkeypatch.setattr("processor.processor.project_full_sync", boom)
    assert proc._run_startup_full_sync("kitsu-p1", "proj1") is False
    sync_events = [
        ev for ev in client.events.values() if ev["topic"] == "kitsu.sync"
    ]
    assert len(sync_events) == 2
    assert sync_events[1]["status"] == "failed"
    assert "super-secret-password" not in sync_events[1]["description"]
    assert "super-secret-password" not in sync_events[1]["payload"]["error"]


def test_inbound_handler_preserves_resolved_project_for_older_zou():
    """Resolved project_id on task:update without project_id is recorded."""
    client = _RecordingAyonClient()
    proc = _make_processor(client)

    original_data = {"task_id": "t-legacy"}

    def legacy_task_handler(_proc, event_data):
        # Simulate create_or_update_task resolving project_id from gazu
        event_data["project_id"] = "kitsu-p1"
        return _FakeHttpResponse(500, detail="Validation failed")

    assert (
        proc._run_inbound_handler(
            "task:update", legacy_task_handler, original_data
        )
        is None
    )
    # Caller's original dict is not mutated
    assert "project_id" not in original_data

    inbound_events = [
        ev
        for ev in client.events.values()
        if ev["topic"] == "kitsu.inbound_sync"
    ]
    assert len(inbound_events) == 1
    assert inbound_events[0]["project"] == "proj1"
    assert inbound_events[0]["status"] == "failed"


# ---------------------------------------------------------------------------
# Server endpoints helpers: init_pairing.sync_request & sync_status
# ---------------------------------------------------------------------------


def _install_ayon_server_stubs(monkeypatch, fake_postgres, fake_events):
    """Install minimal ayon_server stubs so server modules load offline."""

    class _BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def dict(self, by_alias: bool = False):
            return dict(self.__dict__)

    class _BadRequestException(Exception):
        pass

    class _ConflictException(Exception):
        pass

    ayon_server_mod = types.ModuleType("ayon_server")
    entities_mod = types.ModuleType("ayon_server.entities")
    entities_mod.UserEntity = SimpleNamespace

    events_mod = types.ModuleType("ayon_server.events")
    events_mod.dispatch_event = fake_events["dispatch_event"]
    events_mod.update_event = fake_events["update_event"]

    exceptions_mod = types.ModuleType("ayon_server.exceptions")
    exceptions_mod.BadRequestException = _BadRequestException
    exceptions_mod.ConflictException = _ConflictException

    helpers_mod = types.ModuleType("ayon_server.helpers")
    deploy_mod = types.ModuleType("ayon_server.helpers.deploy_project")
    deploy_mod.create_project_from_anatomy = fake_events.get(
        "create_project_from_anatomy"
    )

    lib_mod = types.ModuleType("ayon_server.lib")
    pg_mod = types.ModuleType("ayon_server.lib.postgres")
    pg_mod.Postgres = fake_postgres

    types_mod = types.ModuleType("ayon_server.types")
    types_mod.PROJECT_CODE_REGEX = ".*"
    types_mod.PROJECT_NAME_REGEX = ".*"
    types_mod.Field = lambda default=None, **_kw: default
    types_mod.OPModel = _BaseModel

    for name, mod in {
        "ayon_server": ayon_server_mod,
        "ayon_server.entities": entities_mod,
        "ayon_server.events": events_mod,
        "ayon_server.exceptions": exceptions_mod,
        "ayon_server.helpers": helpers_mod,
        "ayon_server.helpers.deploy_project": deploy_mod,
        "ayon_server.lib": lib_mod,
        "ayon_server.lib.postgres": pg_mod,
        "ayon_server.types": types_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    return _BadRequestException


def _load_server_module(monkeypatch, module_name: str, file_path: Path):
    """Load a server/kitsu module under a clean fake package namespace."""
    pkg_name = "_test_kitsu_srv"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(file_path.parent)]
    monkeypatch.setitem(sys.modules, pkg_name, pkg_mod)

    # Stub sibling .anatomy used by init_pairing.py
    anatomy_mod = types.ModuleType(f"{pkg_name}.anatomy")
    anatomy_mod.get_kitsu_project_anatomy = None
    monkeypatch.setitem(sys.modules, f"{pkg_name}.anatomy", anatomy_mod)

    full_name = f"{pkg_name}.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, full_name, mod)
    spec.loader.exec_module(mod)
    return mod


def test_server_sync_request_returns_event_ids_and_validates_pairing(
    monkeypatch,
):
    """sync_request rejects unpaired projects and returns event IDs."""
    dispatched = []
    updated = []

    class FakePostgres:
        mode = "unpaired"

        @classmethod
        async def iterate(cls, _query, *_args):
            if cls.mode == "unpaired":
                return
            yield {"kitsu_project_id": "kitsu-123"}

        @classmethod
        async def fetch(cls, query, *_args):
            if "SELECT id FROM events" in query:
                if cls.mode == "existing":
                    return [("req-ev-1",)]
                return []
            if "UPDATE events SET" in query:
                return [("sync-ev-1",)]
            return []

    async def fake_dispatch(topic, **kwargs):
        dispatched.append((topic, kwargs))
        return "new-req-ev-9"

    async def fake_update(event_id, **kwargs):
        updated.append((event_id, kwargs))

    bad_req_cls = _install_ayon_server_stubs(
        monkeypatch,
        FakePostgres,
        {"dispatch_event": fake_dispatch, "update_event": fake_update},
    )
    mod = _load_server_module(
        monkeypatch,
        "init_pairing",
        REPO_ROOT / "server" / "kitsu" / "init_pairing.py",
    )
    user = SimpleNamespace(name="admin")

    # 1. Unpaired project raises BadRequestException
    FakePostgres.mode = "unpaired"
    with pytest.raises(bad_req_cls, match="not paired"):
        _run_coro(mod.sync_request("unpaired_proj", user))

    # 2. First sync dispatches new kitsu.sync_request and returns event_id
    FakePostgres.mode = "new"
    res_new = _run_coro(mod.sync_request("paired_proj", user))
    assert res_new.event_id == "new-req-ev-9"
    assert res_new.sync_event_id is None
    assert res_new.status == "pending"
    assert dispatched[0][0] == "kitsu.sync_request"

    # 3. Repeat sync restarts existing kitsu.sync and returns sync_event_id
    FakePostgres.mode = "existing"
    res_restart = _run_coro(mod.sync_request("paired_proj", user))
    assert res_restart.event_id == "req-ev-1"
    assert res_restart.sync_event_id == "sync-ev-1"
    assert res_restart.status == "restarted"
    assert updated[0][0] == "req-ev-1"


def test_server_get_sync_status_aggregates_project_and_service_state(
    monkeypatch,
):
    """get_sync_status handles retries, expiry, heartbeats, and settings."""
    now = datetime.now(timezone.utc)
    stale_req = now - timedelta(days=4)
    stale_hb = now - timedelta(minutes=10)
    fresh_hb = now - timedelta(seconds=30)

    class FakePostgres:
        service_rows = [{"is_running": True, "last_seen": stale_hb}]

        @classmethod
        async def fetch(cls, query, *_args):
            if "FROM projects" in query:
                return [
                    {"name": "proj_a", "kitsu_project_id": "kp-a"},
                    {"name": "proj_b", "kitsu_project_id": "kp-b"},
                    {"name": "proj_c", "kitsu_project_id": "kp-c"},
                ]
            if "WHERE topic = 'kitsu.sync'" in query:
                return [
                    {
                        "id": "ev-sync-a",
                        "topic": "kitsu.sync",
                        "project_name": "proj_a",
                        "depends_on": "ev-req-a",
                        "status": "failed",
                        "retries": 1,
                        "description": "Sync failed: timeout",
                        "payload": {"error": "Kitsu HTTP 504"},
                        "updated_at": now,
                    }
                ]
            if "WHERE topic = 'kitsu.sync_request'" in query:
                return [
                    {
                        "id": "ev-req-b",
                        "topic": "kitsu.sync_request",
                        "project_name": "proj_b",
                        "status": "finished",
                        "description": "Sync request from Kitsu",
                        "payload": {},
                        "updated_at": now,
                    },
                    {
                        "id": "ev-req-c",
                        "topic": "kitsu.sync_request",
                        "project_name": "proj_c",
                        "status": "finished",
                        "description": "Sync request from Kitsu",
                        "payload": {},
                        "updated_at": stale_req,
                    },
                ]
            if "WHERE topic = 'kitsu.outbound_sync'" in query:
                return [
                    {
                        "id": "ev-out-a",
                        "topic": "kitsu.outbound_sync",
                        "project_name": "proj_a",
                        "status": "finished",
                        "description": "Applied: task status updated",
                        "payload": {},
                        "updated_at": now,
                    }
                ]
            if "WHERE topic = 'kitsu.inbound_sync'" in query:
                return []
            if "FROM services" in query:
                return cls.service_rows
            if "WHERE topic = 'log.error'" in query:
                return [
                    {
                        "id": "ev-log-1",
                        "topic": "log.error",
                        "status": "finished",
                        "description": "Kitsu processor error",
                        "payload": {"message": "Kitsu login failed"},
                        "updated_at": now,
                    }
                ]
            return []

    async def _noop(*_a, **_k):
        return None

    _install_ayon_server_stubs(
        monkeypatch,
        FakePostgres,
        {"dispatch_event": _noop, "update_event": _noop},
    )
    mod = _load_server_module(
        monkeypatch,
        "sync_status",
        REPO_ROOT / "server" / "kitsu" / "sync_status.py",
    )

    settings_calls = []

    class FakeAddon:
        name = "kitsu"

        async def get_project_settings(self, project_name: str) -> Any:
            settings_calls.append(project_name)
            return SimpleNamespace(
                sync_settings=SimpleNamespace(
                    two_way_sync=SimpleNamespace(
                        enabled=(project_name == "proj_a")
                    )
                )
            )

    # 1. Stale heartbeat -> processor_running is False
    result = _run_coro(mod.get_sync_status(FakeAddon()))
    assert result.processor_running is False
    assert result.last_service_error.error == "Kitsu login failed"
    assert len(settings_calls) == 3

    proj_a = result.projects["proj_a"]
    assert proj_a.two_way_sync_enabled is True
    assert proj_a.full_sync.status == "failed"
    assert proj_a.full_sync.retryable is True
    assert proj_a.full_sync.error == "Kitsu HTTP 504"
    assert proj_a.last_outbound.status == "finished"

    proj_b = result.projects["proj_b"]
    assert proj_b.two_way_sync_enabled is False
    assert proj_b.full_sync.status == "pending"
    assert "waiting for Kitsu processor" in proj_b.full_sync.description

    # >3-day unenrolled request is reported as expired (retryable via Sync now)
    proj_c = result.projects["proj_c"]
    assert proj_c.full_sync.status == "expired"

    # 2. Fresh heartbeat + include_settings=False skips settings queries
    settings_calls.clear()
    FakePostgres.service_rows = [{"is_running": True, "last_seen": fresh_hb}]
    result_fast = _run_coro(
        mod.get_sync_status(FakeAddon(), include_settings=False)
    )
    assert result_fast.processor_running is True
    assert settings_calls == []

    # 3. No managed service rows -> processor_running is None (unknown)
    FakePostgres.service_rows = []
    result_unmanaged = _run_coro(
        mod.get_sync_status(FakeAddon(), include_settings=False)
    )
    assert result_unmanaged.processor_running is None


def test_server_sync_status_endpoint_requires_manager(monkeypatch):
    """KitsuAddon.sync_status rejects non-manager users."""
    called = []

    class _ForbiddenException(Exception):
        pass

    class _InvalidSettingsException(Exception):
        pass

    class _BaseServerAddon:
        pass

    fastapi_mod = types.ModuleType("fastapi")
    fastapi_resp_mod = types.ModuleType("fastapi.responses")
    fastapi_resp_mod.JSONResponse = dict
    monkeypatch.setitem(sys.modules, "fastapi", fastapi_mod)
    monkeypatch.setitem(sys.modules, "fastapi.responses", fastapi_resp_mod)

    ayon_server_mod = types.ModuleType("ayon_server")
    addons_mod = types.ModuleType("ayon_server.addons")
    addons_mod.BaseServerAddon = _BaseServerAddon
    api_mod = types.ModuleType("ayon_server.api")
    deps_mod = types.ModuleType("ayon_server.api.dependencies")
    deps_mod.CurrentUser = SimpleNamespace
    exc_mod = types.ModuleType("ayon_server.exceptions")
    exc_mod.ForbiddenException = _ForbiddenException
    exc_mod.InvalidSettingsException = _InvalidSettingsException
    secrets_mod = types.ModuleType("ayon_server.secrets")
    secrets_mod.Secrets = SimpleNamespace

    for name, mod in {
        "ayon_server": ayon_server_mod,
        "ayon_server.addons": addons_mod,
        "ayon_server.api": api_mod,
        "ayon_server.api.dependencies": deps_mod,
        "ayon_server.exceptions": exc_mod,
        "ayon_server.secrets": secrets_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    pkg_name = "_test_kitsu_addon_pkg"
    pkg_mod = types.ModuleType(pkg_name)
    pkg_mod.__path__ = [str(REPO_ROOT / "server")]
    monkeypatch.setitem(sys.modules, pkg_name, pkg_mod)

    kitsu_pkg = types.ModuleType(f"{pkg_name}.kitsu")
    kitsu_pkg.Kitsu = object
    kitsu_pkg.KitsuMock = object
    monkeypatch.setitem(sys.modules, f"{pkg_name}.kitsu", kitsu_pkg)

    init_pairing_mod = types.ModuleType(f"{pkg_name}.kitsu.init_pairing")
    init_pairing_mod.InitPairingRequest = object
    init_pairing_mod.SyncRequestResponseModel = object
    init_pairing_mod.init_pairing = None
    init_pairing_mod.sync_request = None
    monkeypatch.setitem(
        sys.modules, f"{pkg_name}.kitsu.init_pairing", init_pairing_mod
    )

    pairing_list_mod = types.ModuleType(f"{pkg_name}.kitsu.pairing_list")
    pairing_list_mod.PairingItemModel = object
    pairing_list_mod.get_pairing_list = None
    monkeypatch.setitem(
        sys.modules, f"{pkg_name}.kitsu.pairing_list", pairing_list_mod
    )

    async def fake_get_sync_status(_addon, *, include_settings: bool = True):
        called.append(include_settings)
        return {"ok": True}

    sync_status_mod = types.ModuleType(f"{pkg_name}.kitsu.sync_status")
    sync_status_mod.SyncStatusResponseModel = object
    sync_status_mod.get_sync_status = fake_get_sync_status
    monkeypatch.setitem(
        sys.modules, f"{pkg_name}.kitsu.sync_status", sync_status_mod
    )

    user_list_mod = types.ModuleType(f"{pkg_name}.kitsu.user_list")
    user_list_mod.get_user_sync_list = None
    monkeypatch.setitem(
        sys.modules, f"{pkg_name}.kitsu.user_list", user_list_mod
    )

    push_mod = types.ModuleType(f"{pkg_name}.kitsu.push")
    push_mod.PushEntitiesRequestModel = object
    push_mod.RemoveEntitiesRequestModel = object
    push_mod.push_entities = None
    push_mod.remove_entities = None
    monkeypatch.setitem(sys.modules, f"{pkg_name}.kitsu.push", push_mod)

    settings_mod = types.ModuleType(f"{pkg_name}.settings")
    settings_mod.KitsuSettings = object
    settings_mod.DEFAULT_VALUES = {}
    settings_mod.convert_settings_overrides = None
    monkeypatch.setitem(sys.modules, f"{pkg_name}.settings", settings_mod)

    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.__init__", REPO_ROOT / "server" / "__init__.py"
    )
    addon_mod = importlib.util.module_from_spec(spec)
    addon_mod.__package__ = pkg_name
    monkeypatch.setitem(sys.modules, f"{pkg_name}.__init__", addon_mod)
    spec.loader.exec_module(addon_mod)

    addon = addon_mod.KitsuAddon()
    artist = SimpleNamespace(is_manager=False)
    manager = SimpleNamespace(is_manager=True)

    with pytest.raises(_ForbiddenException, match="Only managers"):
        _run_coro(addon.sync_status(artist))
    assert called == []

    res = _run_coro(addon.sync_status(manager, include_settings=False))
    assert res == {"ok": True}
    assert called == [False]

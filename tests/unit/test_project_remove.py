"""Project removal regressions; run with the AYON backend dependencies.

    python -m unittest discover -s tests/unit -p test_project_remove.py
"""

import asyncio
import unittest
from importlib.util import find_spec
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

if find_spec("ayon_server") is None:
    raise unittest.SkipTest(
        "Project removal tests require AYON backend dependencies"
    )

import httpx
from ayon_server.exceptions import NotFoundException

from server.kitsu import push
from server.settings import DEFAULT_VALUES, KitsuSettings


class ProjectRemovalTests(unittest.IsolatedAsyncioTestCase):
    """Exercise the real dispatcher and helper without deleting projects."""

    def setUp(self):
        self.settings = KitsuSettings(**DEFAULT_VALUES)
        self.addon = SimpleNamespace(
            get_studio_settings=AsyncMock(return_value=self.settings)
        )
        self.user = SimpleNamespace(name="test-manager")
        self.project = SimpleNamespace(
            name="test_project", data={"kitsuProjectId": "kitsu-project-id"}
        )
        self.entity = {
            "id": "kitsu-project-id",
            "type": "Project",
            "ayon_server_url": "http://ayon.invalid",
        }
        self.payload = push.RemoveEntitiesRequestModel(
            project_name=self.project.name, entities=[self.entity]
        )
        self.requests = []
        self.status_code = 204
        self.transport_error = None
        client_cls = httpx.AsyncClient
        self.client_cls = client_cls

        def respond(request):
            self.requests.append(request)
            if self.transport_error:
                raise self.transport_error
            return httpx.Response(self.status_code)

        self.load = self.enterContext(
            patch.object(
                push.ProjectEntity, "load",
                new=AsyncMock(return_value=self.project),
            )
        )
        self.session = self.enterContext(
            patch.object(
                push.Session, "create",
                new=AsyncMock(
                    return_value=SimpleNamespace(token="test-token")
                ),
            )
        )
        self.client = self.enterContext(
            patch.object(
                push.httpx, "AsyncClient",
                side_effect=lambda: client_cls(
                    transport=httpx.MockTransport(respond)
                ),
            )
        )
        self.update = self.enterContext(
            patch.object(push, "update_project", new=AsyncMock())
        )

    async def remove(self):
        """Run the project-removal request with the current test state."""
        return await push.remove_entities(
            self.addon, self.user, self.payload
        )

    async def test_disabled_setting_does_not_load_or_delete_project(self):
        result = await self.remove()
        self.assertEqual(result, {"folders": {}, "tasks": {}})
        self.load.assert_not_awaited()
        self.session.assert_not_awaited()
        self.client.assert_not_called()
        self.update.assert_not_awaited()

    async def test_enabled_setting_deletes_paired_project_through_rest(self):
        self.settings.sync_settings.delete_projects = True
        await self.remove()
        self.load.assert_awaited_once_with(self.project.name)
        self.session.assert_awaited_once_with(self.user)
        self.update.assert_not_awaited()
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request.method, "DELETE")
        self.assertEqual(
            str(request.url), "http://ayon.invalid/api/projects/test_project"
        )
        self.assertEqual(request.headers["Authorization"], "Bearer test-token")

    async def test_mismatched_pairing_is_not_deleted(self):
        self.settings.sync_settings.delete_projects = True
        self.project.data["kitsuProjectId"] = "another-kitsu-project"
        await self.remove()
        self.session.assert_not_awaited()
        self.client.assert_not_called()

    async def test_unpaired_project_is_not_deleted(self):
        self.settings.sync_settings.delete_projects = True
        self.project.data.clear()
        await self.remove()
        self.client.assert_not_called()

    async def test_missing_id_is_rejected_before_deletion(self):
        self.settings.sync_settings.delete_projects = True
        self.payload.entities[0].pop("id")
        with self.assertRaisesRegex(ValueError, "Key 'id' not set"):
            await self.remove()
        self.client.assert_not_called()

    async def test_empty_id_is_rejected_before_deletion(self):
        self.settings.sync_settings.delete_projects = True
        self.payload.entities[0]["id"] = ""
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            await self.remove()
        self.client.assert_not_called()

    async def test_already_missing_project_is_a_noop(self):
        self.settings.sync_settings.delete_projects = True
        self.load.side_effect = NotFoundException("Already removed")
        self.assertEqual(await self.remove(), {"folders": {}, "tasks": {}})
        self.client.assert_not_called()

    async def test_duplicate_project_entry_reloads_deleted_project(self):
        self.settings.sync_settings.delete_projects = True
        self.payload.entities.append(dict(self.entity))
        self.load.side_effect = [
            self.project, NotFoundException("Already removed")
        ]
        await self.remove()
        self.assertEqual(self.load.await_count, 2)
        self.assertEqual(len(self.requests), 1)

    async def test_http_failure_is_not_reported_as_success(self):
        self.settings.sync_settings.delete_projects = True
        for status in (403, 404, 500):
            with self.subTest(status=status):
                self.status_code = status
                with self.assertRaises(httpx.HTTPStatusError) as raised:
                    await self.remove()
                self.assertEqual(raised.exception.response.status_code, status)

    async def test_concurrent_deletion_accepts_confirmed_absence(self):
        self.settings.sync_settings.delete_projects = True
        both_loaded = asyncio.Event()
        loads = 0

        async def load(name):
            nonlocal loads
            loads += 1
            if loads > 2:
                raise NotFoundException("Already removed")
            if loads == 2:
                both_loaded.set()
            await both_loaded.wait()
            return self.project

        self.load.side_effect = load
        statuses = iter((204, 404))
        self.client.side_effect = lambda: self.client_cls(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(next(statuses))
            )
        )
        results = await asyncio.wait_for(
            asyncio.gather(self.remove(), self.remove()), timeout=2
        )
        self.assertEqual(results, [{"folders": {}, "tasks": {}}] * 2)
        self.assertEqual(self.load.await_count, 3)

    async def test_404_confirmation_errors_are_not_swallowed(self):
        self.settings.sync_settings.delete_projects = True
        self.status_code = 404
        self.load.side_effect = [
            self.project, RuntimeError("Database unavailable")
        ]
        with self.assertRaisesRegex(RuntimeError, "Database unavailable"):
            await self.remove()

    async def test_transport_failure_is_not_reported_as_success(self):
        self.settings.sync_settings.delete_projects = True
        self.transport_error = httpx.ConnectError("Server unavailable")
        with self.assertRaises(httpx.ConnectError):
            await self.remove()

    async def test_other_project_load_failures_are_not_swallowed(self):
        self.settings.sync_settings.delete_projects = True
        self.load.side_effect = RuntimeError("Database unavailable")
        with self.assertRaisesRegex(RuntimeError, "Database unavailable"):
            await self.remove()
        self.client.assert_not_called()


if __name__ == "__main__":
    unittest.main()

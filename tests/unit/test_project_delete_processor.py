"""Processor deletion regressions; run with the processor dependencies.

    PYTHONPATH=services/processor python -m unittest discover \
        -s tests/unit -p test_project_delete_processor.py
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests
from ayon_api.exceptions import HTTPRequestError
from ayon_api.server_api import RestApiResponse

from processor import update_from_kitsu


class ProcessorProjectDeletionTests(unittest.TestCase):
    """Check event routing without making requests to either server."""

    def test_paired_event_posts_complete_removal_payload(self):
        parent = SimpleNamespace(
            entrypoint="/addons/kitsu/test",
            get_paired_ayon_project=lambda project_id: "test_project",
        )
        with (
            patch.object(update_from_kitsu.ayon_api, "post") as post,
            patch.object(
                update_from_kitsu.ayon_api, "get_base_url",
                return_value="http://ayon.invalid",
            ),
            patch.object(
                update_from_kitsu.gazu.project, "get_project"
            ) as get_project,
        ):
            result = update_from_kitsu.delete_project(
                parent, {"project_id": "deleted-kitsu-project"}
            )
            post.assert_called_once_with(
                "/addons/kitsu/test/remove",
                project_name="test_project",
                entities=[{
                    "id": "deleted-kitsu-project",
                    "type": "Project",
                    "ayon_server_url": "http://ayon.invalid",
                }],
            )
            self.assertIs(result, post.return_value)
            post.return_value.raise_for_status.assert_called_once_with()
            get_project.assert_not_called()

    def test_failed_removal_response_raises_for_event_listener(self):
        parent = SimpleNamespace(
            entrypoint="/addons/kitsu/test",
            get_paired_ayon_project=lambda project_id: "test_project",
        )
        for status in (403, 500):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                response.url = "http://ayon.invalid/api/addons/kitsu/test/remove"
                with (
                    patch.object(
                        update_from_kitsu.ayon_api, "post",
                        return_value=RestApiResponse(response, data={}),
                    ),
                    patch.object(
                        update_from_kitsu.ayon_api, "get_base_url",
                        return_value="http://ayon.invalid",
                    ),
                ):
                    with self.assertRaises(HTTPRequestError):
                        update_from_kitsu.delete_project(
                            parent, {"project_id": "deleted-kitsu-project"}
                        )

    def test_unpaired_event_does_not_send_request(self):
        parent = SimpleNamespace(
            get_paired_ayon_project=lambda project_id: None,
        )
        with (
            patch.object(update_from_kitsu.ayon_api, "post") as post,
            patch.object(
                update_from_kitsu.ayon_api, "get_base_url"
            ) as get_base_url,
        ):
            self.assertIsNone(update_from_kitsu.delete_project(
                parent, {"project_id": "unpaired-kitsu-project"}
            ))
            post.assert_not_called()
            get_base_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()

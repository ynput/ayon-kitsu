"""Isolation and socket cleanup for outbound tests on live servers."""

import uuid

import pytest


@pytest.fixture
def isolated_outbound_live(monkeypatch):
    """Restrict enrollment to this test's pairings and close its listeners.

    Args:
        monkeypatch: Pytest patch manager.

    Yields:
        Control while the live test runs with an isolated event topic.
    """
    import ayon_api
    from processor.outbound import runner
    from processor.processor import KitsuProcessor

    original_filter = runner.build_enroll_filter
    original_init = KitsuProcessor.__init__
    original_enroll = ayon_api.enroll_event_job
    processors = []

    def scoped_filter(topics):
        result = original_filter(topics) or {
            "operator": "and",
            "conditions": [],
        }
        condition = {
            "key": "project",
            "operator": "like",
            "value": "test_live_%",
        }
        if processors:
            condition = {
                "key": "project",
                "operator": "in",
                "value": list(processors[-1].get_outbound_pairings()),
            }
        result["conditions"].append(condition)
        return result

    def track_processor(self):
        processors.append(self)
        original_init(self)

    def scoped_enroll(*args, **kwargs):
        topics = kwargs.get("source_topic") or []
        if isinstance(topics, str):
            topics = [topics]
        kwargs["events_filter"] = scoped_filter(topics)
        return original_enroll(*args, **kwargs)

    monkeypatch.setattr(runner, "build_enroll_filter", scoped_filter)
    monkeypatch.setattr(
        runner.OutboundJobRunner,
        "TARGET_TOPIC",
        "kitsu.live_validation." + uuid.uuid4().hex,
    )
    monkeypatch.setattr(KitsuProcessor, "__init__", track_processor)
    monkeypatch.setattr(ayon_api, "enroll_event_job", scoped_enroll)
    yield
    for processor in processors:
        processor.stop()
        client = getattr(processor, "event_client", None)
        if client is not None:
            client.disconnect()

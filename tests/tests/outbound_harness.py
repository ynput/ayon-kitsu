"""Shared harness for OutboundJobRunner tests.

Builds a runner wired to the in-memory fakes so each test module does
not need to repeat the gate / watcher / identity wiring.
"""

from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional
from unittest.mock import MagicMock

from processor.outbound.identity import IdentityResolver
from processor.outbound.runner import OutboundJobRunner
from processor.outbound.settings_watch import GateHistory, SettingsWatcher

from .outbound_fakes import FakeAyonStore, FakeClock, FakeKitsuWriter

PROJECT = "test-project"
KITSU_PROJECT = "kitsu-proj-1"
SENDER = "kitsu-processor-test"

ALL_CATEGORIES = (
    "task_status",
    "task_assignees",
    "entity_attributes",
    "entity_creation",
    "entity_rename",
    "entity_deletion",
)
SLICE2_CATEGORIES = ("task_assignees", "entity_attributes")
SLICE3_CATEGORIES = ("entity_creation", "entity_rename", "entity_deletion")


def build_runner(
    enable: Iterable[str] = (),
    *,
    disable: Iterable[str] = (),
    policy: str = "kitsu_wins",
    clock: Optional[FakeClock] = None,
    store: Optional[FakeAyonStore] = None,
    writer: Optional[FakeKitsuWriter] = None,
) -> SimpleNamespace:
    """Build a runner against fakes with the given categories enabled.

    ``task_status`` is enabled by default (the fake store default). Pass
    it in ``disable`` to turn it off.

    Args:
        enable: Extra categories to enable in settings and gate history.
        disable: Categories to force off.
        policy: Conflict policy (``kitsu_wins`` or ``ayon_wins``).
        clock: Optional clock to reuse.
        store: Optional AYON store to reuse.
        writer: Optional Kitsu writer to reuse.

    Returns:
        Namespace with ``clock``, ``store``, ``writer``, ``runner``,
        ``processor``, ``watcher`` and ``gate_history``.
    """
    clock = clock or FakeClock(1000.0)
    store = store or FakeAyonStore(clock=clock)
    writer = writer or FakeKitsuWriter()

    categories: Dict[str, bool] = {c: False for c in ALL_CATEGORIES}
    categories["task_status"] = True
    categories.update({c: True for c in enable})
    categories.update({c: False for c in disable})

    sync_cfg = store.studio_settings["sync_settings"]["two_way_sync"]
    sync_cfg.update(categories)
    sync_cfg["conflict_policy"] = policy

    processor = MagicMock()
    processor.sender = SENDER
    processor.pairing_list = {PROJECT: KITSU_PROJECT}

    gate_history = GateHistory(store, clock=clock)
    gate_history.record_observation(
        PROJECT,
        {
            "valid": True,
            "master": True,
            "categories": categories,
            "conflict_policy": policy,
        },
        now=clock(),
    )
    watcher = SettingsWatcher(
        store,
        pairing_list_getter=lambda: {PROJECT: KITSU_PROJECT},
        gate_history=gate_history,
        clock=clock,
    )
    watcher.refresh()

    runner = OutboundJobRunner(
        processor=processor,
        clock=clock,
        ayon_client=store,
        writer=writer,
        settings_watcher=watcher,
        gate_history=gate_history,
        identity_resolver=IdentityResolver(store, writer),
        sender=SENDER,
    )
    return SimpleNamespace(
        clock=clock,
        store=store,
        writer=writer,
        runner=runner,
        processor=processor,
        watcher=watcher,
        gate_history=gate_history,
    )


def setup_runner(enabled: bool = True) -> tuple:
    """Return ``(clock, store, writer, runner, processor)``.

    Args:
        enabled: Enable the ``entity_deletion`` category when true.
    """
    h = build_runner(("entity_deletion",) if enabled else ())
    return h.clock, h.store, h.writer, h.runner, h.processor


def add_event(
    store: FakeAyonStore,
    event_id: str,
    topic: str,
    entity_id: str,
    **kwargs: Any,
) -> Any:
    """Add a user-originated source event for ``PROJECT``."""
    return store.add_source_event(
        event_id=event_id,
        topic=topic,
        project_name=PROJECT,
        created_at=kwargs.pop("created_at", 1010.0),
        summary={"entityId": entity_id},
        user="test-user",
        **kwargs,
    )

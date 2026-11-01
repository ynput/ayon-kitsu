"""Feasibility probe: Unknown_Toggle_Gap detection and event skips.

Measures processor restart behavior, Unknown_Toggle_Gap duration in seconds,
and count of events skipped under Requirement 4.12 with toggle state unknown.

Validates: Requirements 4.12, 4.13
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent.parent
for _p in [
    _ROOT / "services" / "processor",
    _ROOT / "server" / "kitsu",
    _ROOT / "server" / "settings",
    _ROOT / "tests",
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from processor.outbound.gating import (
    STATE_UNKNOWN_GAP,
    find_unknown_gap,
    gate_decision,
    toggles_at,
)


def probe_restart_gap_simulation(
    gap_duration_s: float = 120.0,
    settings_changed: bool = True,
    event_count: int = 5,
) -> Dict[str, Any]:
    """Simulate a processor stop, settings change, and event processing.

    Args:
        gap_duration_s: Duration in seconds the processor was stopped.
        settings_changed: Whether settings changed while stopped.
        event_count: Number of status events created while stopped.

    Returns:
        Dict with gap duration, settings changes, and skipped events count.
    """
    now = 2000.0
    last_observed_at = now - gap_duration_s

    # Settings changed event timestamps while stopped
    settings_changes = [last_observed_at + 10.0] if settings_changed else []

    # Detect gap
    gap = find_unknown_gap(last_observed_at, now, settings_changes)
    gaps: List[Dict[str, Any]] = [gap] if gap else []

    # Simulate events created during the gap
    skipped_count = 0
    reasons = []

    history = [
        {
            "project": "test_project",
            "observedAt": last_observed_at - 10.0,
            "toggles": {
                "valid": True,
                "master": True,
                "categories": {"task_status": True},
            },
        }
    ]
    current_toggles = {
        "valid": True,
        "master": True,
        "categories": {"task_status": True},
    }

    for i in range(event_count):
        evt_created_at = last_observed_at + 20.0 + (i * 5.0)
        t_state = toggles_at(history, gaps, evt_created_at)
        g_dec = gate_decision("task_status", t_state, current_toggles)
        if not g_dec["allowed"]:
            skipped_count += 1
            reasons.append(g_dec["reason"])

    return {
        "gap_detected": gap is not None,
        "unknown": gap.get("unknown") if gap else False,
        "duration_s": gap.get("durationS") if gap else 0.0,
        "settings_changes": len(settings_changes),
        "created_events": event_count,
        "skipped_events": skipped_count,
        "reasons": reasons[:2],
    }


def run_restart_probe() -> Dict[str, Any]:
    """Execute restart gap probe."""
    res = probe_restart_gap_simulation(
        gap_duration_s=300.0,
        settings_changed=True,
        event_count=8,
    )
    return res


def main() -> None:
    """Run restart probe and print results."""
    res = run_restart_probe()
    print("=== Unknown_Toggle_Gap and Restart Skip Probe ===")
    print(f"Gap detected: {res['gap_detected']}")
    print(f"Unknown toggle state: {res['unknown']}")
    print(f"Gap duration: {res['duration_s']} s")
    print(f"Settings changes while stopped: {res['settings_changes']}")
    print(f"Events created during gap: {res['created_events']}")
    print(f"Events skipped under Req 4.12: {res['skipped_events']}")
    print(f"Sample skip reason: {res['reasons']}")


if __name__ == "__main__":
    main()

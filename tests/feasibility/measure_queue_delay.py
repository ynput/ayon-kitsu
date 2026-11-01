"""Feasibility measurement: global queue retry delay and reaper delay.

Measures the delay in milliseconds that an Outbound_Job failing all 4 retry
attempts imposes on the next Outbound_Job of a different AYON entity
(Requirement 4.15). Also reports the gap-2 reaper delay for abandoned jobs.

Validates: Requirements 4.15
"""

from __future__ import annotations

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

from processor.outbound.constants import RETRY_DELAY_S
from processor.outbound.retry import retry_due


def simulate_4_attempt_queue_delay() -> Dict[str, Any]:
    """Measure delay imposed by a 4-attempt retrying job on the next job.

    Simulates entity A failing attempts 1-3 with Retryable_Kitsu_Failure
    and attempt 4 failing final, with entity B created shortly after entity A.

    Returns:
        Dict with total delay in milliseconds, attempt timeline, and details.
    """
    # Monotonic simulation clock (epoch seconds)
    sim_clock = 1000.0

    # Entity A created at t=1000.0
    # Entity B created at t=1005.0 (while A is attempting/retrying)
    t_a_created = sim_clock
    t_b_created = sim_clock + 5.0

    timeline: List[Dict[str, Any]] = []

    # Attempt 1 of A starts at t=1000.0, fails at t=1001.0
    sim_clock += 1.0
    last_failed_a = sim_clock
    timeline.append({"job": "A", "attempt": 1, "failed_at": last_failed_a})

    # Retry hold requires at least 10s before attempt 2
    # Advance until attempt 2 is due
    while not retry_due(last_failed_a, sim_clock, excluded_s=0.0)["due"]:
        sim_clock += 0.5
    sim_clock += 1.0  # Attempt 2 runs 1s and fails
    last_failed_a = sim_clock
    timeline.append({"job": "A", "attempt": 2, "failed_at": last_failed_a})

    # Advance until attempt 3 is due
    while not retry_due(last_failed_a, sim_clock, excluded_s=0.0)["due"]:
        sim_clock += 0.5
    sim_clock += 1.0  # Attempt 3 runs 1s and fails
    last_failed_a = sim_clock
    timeline.append({"job": "A", "attempt": 3, "failed_at": last_failed_a})

    # Advance until attempt 4 (final) is due
    while not retry_due(last_failed_a, sim_clock, excluded_s=0.0)["due"]:
        sim_clock += 0.5
    sim_clock += 1.0  # Attempt 4 runs 1s and fails final
    timeline.append({"job": "A", "attempt": 4, "final_failed_at": sim_clock})

    # Now Job A is finished (final failure). Next job B can start immediately!
    t_b_first_attempt = sim_clock

    # Delay in milliseconds from Job B's creation time to first attempt
    delay_ms = round((t_b_first_attempt - t_b_created) * 1000.0, 1)

    return {
        "scenario": "4_attempt_retry_queue_delay",
        "job_a_created": t_a_created,
        "job_b_created": t_b_created,
        "job_b_first_attempt": t_b_first_attempt,
        "delay_ms": delay_ms,
        "delay_s": round(delay_ms / 1000.0, 2),
        "attempts_run": 4,
        "min_hold_per_retry_s": RETRY_DELAY_S,
    }


def report_gap_2_reaper_delay() -> Dict[str, Any]:
    """Report expected and measured gap-2 stale job reaper delay.

    A stale job left in progress by another sender is abandoned after
    300 s idle, and the reaper runs every 60 s.

    Returns:
        Dict with idle threshold, reaper interval, and worst-case delay.
    """
    idle_threshold_s = 300.0
    reaper_interval_s = 60.0
    worst_case_delay_s = idle_threshold_s + reaper_interval_s

    return {
        "scenario": "gap_2_stale_job_reaper",
        "idle_threshold_s": idle_threshold_s,
        "reaper_interval_s": reaper_interval_s,
        "worst_case_delay_s": worst_case_delay_s,
        "worst_case_delay_ms": worst_case_delay_s * 1000.0,
    }


def main() -> None:
    """Run queue delay measurement and print results."""
    retry_res = simulate_4_attempt_queue_delay()
    reaper_res = report_gap_2_reaper_delay()

    print("=== Global Queue Delay Measurement (Requirement 4.15) ===")
    print(f"4-attempt retry queue delay: {retry_res['delay_ms']} ms "
          f"({retry_res['delay_s']} s)")
    print(f"Gap 2 reaper delay (worst case): "
          f"{reaper_res['worst_case_delay_s']} s")


if __name__ == "__main__":
    main()

"""Purity tests for the outbound pure core (Requirement 14.1).

Asserts that pure modules in ``processor/outbound/`` never import or load
``gazu``, ``ayon_api``, ``requests`` or ``httpx``.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .offline import block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

FORBIDDEN_MODULES = {"gazu", "ayon_api", "requests", "httpx"}
IO_MODULE_FILENAMES = {
    "__init__.py",
    "settings_watch.py",
    "identity.py",
    "kitsu_writer.py",
    "runner.py",
}


def get_pure_modules():
    """Discover all pure modules in the outbound package."""
    # Find services/processor/processor/outbound directory
    tests_dir = Path(__file__).resolve().parent.parent
    worktree_root = tests_dir.parent
    outbound_dir = (
        worktree_root / "services" / "processor" / "processor" / "outbound"
    )
    if not outbound_dir.is_dir():
        pytest.fail(f"Outbound directory not found at {outbound_dir}")

    pure_files = []
    for file_path in outbound_dir.glob("*.py"):
        if file_path.name not in IO_MODULE_FILENAMES:
            pure_files.append(file_path.stem)
    return sorted(pure_files)


@pytest.mark.parametrize("module_name", get_pure_modules())
def test_pure_module_does_not_load_io_libraries(module_name):
    """Import each pure module in a subprocess and verify sys.modules."""
    tests_dir = Path(__file__).resolve().parent.parent
    worktree_root = tests_dir.parent
    processor_dir = str(worktree_root / "services" / "processor")

    code = (
        f"import sys\n"
        f"sys.path.insert(0, {repr(processor_dir)})\n"
        f"import processor.outbound.{module_name}\n"
        f"forbidden = {repr(FORBIDDEN_MODULES)}\n"
        f"loaded = forbidden & set(sys.modules)\n"
        f"assert not loaded, f'Loaded forbidden modules: {{loaded}}'\n"
    )

    env = os.environ.copy()
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (
        f"Module processor.outbound.{module_name} failed purity test:\n"
        f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )

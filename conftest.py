"""Root-level test configuration for the ChuMicro workspace.

Auto-discovers library and support package source roots so that
``pytest`` can resolve imports even without editable installs
(e.g., in CI or on a fresh clone before setup runs).  Also
excludes ``functional_tests/`` from host-side collection unless
``CHUMICRO_DEVICE_RUNTIME`` is set, in which case the
``pytest_device`` plugin routes them to real hardware.

When a functional test file is targeted directly (e.g. via an IDE
play button), ``collect_ignore_glob`` is bypassed.  The
``pytest_collection_modifyitems`` hook catches these and skips them
with a clear message instead of silently running on CPython.

See ``plans/decisions/0009-per-library-test-runs.md`` for the
per-library test isolation strategy.
See ``plans/decisions/0027-device-testing-infrastructure.md`` for
IDE integration via the device plugin.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# When CHUMICRO_DEVICE_RUNTIME is set, functional tests are collected
# and routed to hardware by the pytest_device plugin.  Otherwise they
# are excluded from host-side collection.
_device_runtime = os.environ.get("CHUMICRO_DEVICE_RUNTIME")

if _device_runtime:
    collect_ignore_glob: list[str] = []
    pytest_plugins = ["pytest_device"]
else:
    collect_ignore_glob = ["**/functional_tests/**"]


def pytest_collection_modifyitems(config, items):
    """Skip functional tests that were collected without a device runtime.

    ``collect_ignore_glob`` prevents discovery during directory traversal,
    but IDEs often pass file paths directly (e.g. ``--path <file>``),
    bypassing glob exclusion.  This hook catches those items and marks
    them as skipped so they never silently run on CPython.
    """
    if _device_runtime:
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "Functional tests require a connected device.  "
            "Set CHUMICRO_DEVICE_RUNTIME=micropython (or circuitpython) "
            "in your run configuration to route tests to hardware."
        ),
    )
    for item in items:
        if "functional_tests" in item.nodeid:
            item.add_marker(skip_marker)


def _discover_source_roots() -> list[str]:
    """Return src/ directories for all packages under libraries/ and support/."""
    roots: list[str] = []
    for parent in [ROOT / "support", ROOT / "libraries"]:
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            src = child / "src"
            if src.is_dir():
                roots.append(str(src))
    return roots


for _src_root in _discover_source_roots():
    if _src_root not in sys.path:
        sys.path.insert(0, _src_root)

# scripts/ modules use bare imports (e.g. ``from workspace import ROOT``).
# Add scripts/ to sys.path so tests collected from root can resolve them.
_scripts_dir = str(ROOT / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
